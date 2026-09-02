from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import opentimelineio as otio

from common import REPO_ROOT, ffprobe, media_duration, project_file, read_json


RIGHTS_WARNING = (
    "この動画は個人利用を前提として生成されています。Web上から取得した画像・動画・音声等が含まれる可能性があります。"
    "YouTube、SNS、Web等で公開・配布・商用利用する場合は、使用素材の著作権・ライセンス・利用条件を確認してください。"
)


def rate_time(seconds: float, fps: float) -> otio.opentime.RationalTime:
    # Keep sub-frame precision in OTIO. Rounding every narration segment and
    # gap separately makes the errors accumulate on longer, many-scene videos.
    return otio.opentime.RationalTime(seconds * fps, fps)


def relative_media_url(path: Path, reference_dir: Path) -> str:
    try:
        return Path(os.path.relpath(path.resolve(), reference_dir.resolve())).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def external_clip(
    name: str,
    path: Path,
    start: float,
    duration: float,
    fps: float,
    metadata: dict[str, Any],
    reference_dir: Path,
) -> otio.schema.Clip:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".svg"}:
        available_duration = duration
        available_start = 0.0
        source_start = 0.0
    else:
        available_duration = media_duration(path)
        available_start = 0.0
        source_start = start
    reference = otio.schema.ExternalReference(
        target_url=relative_media_url(path, reference_dir),
        available_range=otio.opentime.TimeRange(rate_time(available_start, fps), rate_time(available_duration, fps)),
        metadata=metadata,
    )
    return otio.schema.Clip(
        name=name,
        media_reference=reference,
        source_range=otio.opentime.TimeRange(rate_time(source_start, fps), rate_time(duration, fps)),
        metadata=metadata,
    )


def visual_clips(
    name: str,
    path: Path,
    start: float,
    duration: float,
    fps: float,
    metadata: dict[str, Any],
    reference_dir: Path,
) -> list[otio.schema.Clip]:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".svg"}:
        return [external_clip(name, path, 0, duration, fps, metadata, reference_dir)]

    media_length = media_duration(path)
    if media_length <= 0:
        raise ValueError(f"素材の尺が0秒です: {path}")
    if start < 0 or start >= media_length:
        raise ValueError(f"素材の開始位置が範囲外です: {path} start={start} duration={media_length}")

    clips: list[otio.schema.Clip] = []
    remaining = duration
    source_start = start
    part = 1
    while remaining > 1e-6:
        available = media_length - source_start
        piece_duration = min(remaining, available)
        part_name = name if duration <= available and part == 1 else f"{name} (part {part})"
        part_metadata = {**metadata, "loop_part": part}
        clips.append(external_clip(part_name, path, source_start, piece_duration, fps, part_metadata, reference_dir))
        remaining -= piece_duration
        source_start = 0.0
        part += 1
    return clips


def main() -> int:
    parser = argparse.ArgumentParser(description="Kdenliveへ渡すOpenTimelineIOタイムラインを作ります")
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    project_dir = args.project_dir.resolve()
    project = read_json(project_dir / "project.json")
    timing = read_json(project_dir / "audio" / "timing.json")
    style = read_json(REPO_ROOT / "style.json")
    fps = float(project.get("video", {}).get("fps", style["video"]["fps"]))
    output = project_dir / "timeline" / "edit.otio"
    output.parent.mkdir(parents=True, exist_ok=True)

    timeline = otio.schema.Timeline(name=project["title"])
    timeline.metadata["project"] = {
        "schema_version": project.get("schema_version", 1),
        "project_dir": str(project_dir),
        "subtitles": relative_media_url(project_dir / "subtitles" / "subtitles.ass", output.parent),
        "still_motion": {
            **style.get("editing", {}).get("still_motion", {}),
            **project.get("editing", {}).get("still_motion", {}),
        },
        "rights_warning": RIGHTS_WARNING,
    }

    visual_track = otio.schema.Track(name="V1 Visuals", kind=otio.schema.TrackKind.Video)
    scene_times = {scene["id"]: scene for scene in timing["scenes"]}
    for scene in project["scenes"]:
        visual = scene["visual"]
        scene_timing = scene_times[scene["id"]]
        clips = visual_clips(
            scene.get("label", scene["id"]),
            project_file(project_dir, visual["path"]),
            float(visual.get("source_start", 0)),
            float(scene_timing["duration"]),
            fps,
            {"scene_id": scene["id"], "source_id": visual.get("source_id", ""), "motion": visual.get("motion", "none")},
            output.parent,
        )
        visual_track.extend(clips)
    timeline.tracks.append(visual_track)

    narration_track = otio.schema.Track(name="A1 Narration", kind=otio.schema.TrackKind.Audio)
    for segment in timing["segments"]:
        wav_path = project_file(project_dir, segment["wav"])
        narration_track.append(
            external_clip(
                segment["id"],
                wav_path,
                0,
                float(segment["audio_duration"]),
                fps,
                {"scene_id": segment["scene_id"], "subtitle": segment["subtitle"]},
                output.parent,
            )
        )
        hold_after = float(segment.get("hold_after", 0))
        if hold_after > 0:
            narration_track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(rate_time(0, fps), rate_time(hold_after, fps))))
    timeline.tracks.append(narration_track)

    if project.get("bgm"):
        bgm_path = project_file(project_dir, project["bgm"]["path"])
        bgm_track = otio.schema.Track(name="A2 BGM", kind=otio.schema.TrackKind.Audio)
        for clip in visual_clips(
            "BGM",
            bgm_path,
            0,
            float(timing["total_duration"]),
            fps,
            {"role": "background_music"},
            output.parent,
        ):
            bgm_track.append(clip)
        timeline.tracks.append(bgm_track)

    for scene in timing["scenes"]:
        timeline.tracks.markers.append(
            otio.schema.Marker(
                name=f"Scene {scene['id']}",
                marked_range=otio.opentime.TimeRange(rate_time(float(scene["start"]), fps), rate_time(1 / fps, fps)),
                metadata={"scene_id": scene["id"]},
            )
        )

    otio.adapters.write_to_file(timeline, str(output))
    reread = otio.adapters.read_from_file(str(output))
    summary = {"output": str(output), "tracks": [track.name for track in reread.tracks], "duration": reread.duration().to_seconds()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
