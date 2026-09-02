from __future__ import annotations

import argparse
import json
import math
import os
from fractions import Fraction
from pathlib import Path
from typing import Any

from common import (
    REPO_ROOT,
    ffprobe,
    final_output_path,
    find_executable,
    media_duration,
    project_file,
    read_json,
    run,
    write_json,
)


RIGHTS_WARNING = (
    "この動画は個人利用を前提として生成されています。Web上から取得した画像・動画・音声等が含まれる可能性があります。"
    "YouTube、SNS、Web等で公開・配布・商用利用する場合は、使用素材の著作権・ライセンス・利用条件を確認してください。"
)
SCENE_RENDERER_VERSION = 2


def visual_filter(width: int, height: int, fps: int) -> str:
    """Scale/crop only. Still-image motion is rendered by MLT Transform."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},format=yuv420p"
    )


def image_size(path: Path) -> tuple[int, int]:
    info = ffprobe(path)
    stream = next((item for item in info.get("streams", []) if item.get("codec_type") == "video"), None)
    if not stream or not stream.get("width") or not stream.get("height"):
        raise RuntimeError(f"静止画の寸法を取得できません: {path}")
    return int(stream["width"]), int(stream["height"])


def cover_rect(
    source_width: int,
    source_height: int,
    canvas_width: int,
    canvas_height: int,
    scale: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> tuple[float, float, float, float]:
    """Return a centered, aspect-preserving rectangle that covers the canvas."""
    source_aspect = source_width / source_height
    canvas_aspect = canvas_width / canvas_height
    if source_aspect >= canvas_aspect:
        base_height = float(canvas_height)
        base_width = base_height * source_aspect
    else:
        base_width = float(canvas_width)
        base_height = base_width / source_aspect
    rect_width = base_width * scale
    rect_height = base_height * scale
    x = (canvas_width - rect_width) / 2 + offset_x
    y = (canvas_height - rect_height) / 2 + offset_y
    return x, y, rect_width, rect_height


def format_rect(rect: tuple[float, float, float, float]) -> str:
    return " ".join(f"{value:.3f}" for value in rect) + " 1"


def mlt_transform_animation(
    source_width: int,
    source_height: int,
    canvas_width: int,
    canvas_height: int,
    frames: int,
    motion: str,
    zoom_percent: float,
    pan_percent: float,
) -> str:
    """Build Kdenlive/MLT qtblend Transform keyframes with sinusoidal easing."""
    if frames < 2:
        return format_rect(cover_rect(source_width, source_height, canvas_width, canvas_height))

    zoom_scale = 1 + max(0.0, zoom_percent) / 100
    pan_x = canvas_width * max(0.0, pan_percent) / 100
    pan_y = canvas_height * max(0.0, pan_percent) / 100
    if motion == "zoom_in":
        start = cover_rect(source_width, source_height, canvas_width, canvas_height)
        end = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale)
    elif motion == "zoom_out":
        start = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale)
        end = cover_rect(source_width, source_height, canvas_width, canvas_height)
    elif motion == "pan_left":
        start = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale, pan_x, 0)
        end = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale, -pan_x, 0)
    elif motion == "pan_right":
        start = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale, -pan_x, 0)
        end = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale, pan_x, 0)
    elif motion == "pan_up":
        start = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale, 0, pan_y)
        end = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale, 0, -pan_y)
    elif motion == "pan_down":
        start = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale, 0, -pan_y)
        end = cover_rect(source_width, source_height, canvas_width, canvas_height, zoom_scale, 0, pan_y)
    else:
        raise ValueError(f"未対応の静止画モーションです: {motion}")

    # MLT's `c=` keyframe type is sinusoidal ease-in-out. It gives the
    # Transform effect a gentle start and stop without spline overshoot.
    return f"0c={format_rect(start)};{frames - 1}={format_rect(end)}"


def write_mlt_profile(path: Path, width: int, height: int, fps: float) -> None:
    frame_rate = Fraction(str(fps)).limit_denominator(1001)
    aspect_divisor = math.gcd(width, height)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "description=Video automation project profile",
                f"frame_rate_num={frame_rate.numerator}",
                f"frame_rate_den={frame_rate.denominator}",
                f"width={width}",
                f"height={height}",
                "progressive=1",
                "sample_aspect_num=1",
                "sample_aspect_den=1",
                f"display_aspect_num={width // aspect_divisor}",
                f"display_aspect_den={height // aspect_divisor}",
                "colorspace=709",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def project_relative(path: Path, project_dir: Path) -> str:
    return Path(os.path.relpath(path.resolve(), project_dir.resolve())).as_posix()


def make_mlt_still_clip(
    melt: Path,
    project_dir: Path,
    source: Path,
    output: Path,
    profile: Path,
    frames: int,
    width: int,
    height: int,
    motion: str,
    still_motion: dict[str, Any],
) -> None:
    source_width, source_height = image_size(source)
    animation = mlt_transform_animation(
        source_width,
        source_height,
        width,
        height,
        frames,
        motion,
        float(still_motion.get("max_zoom_percent", 3.0)),
        float(still_motion.get("max_pan_percent", 1.0)),
    )
    run(
        [
            melt,
            "-silent",
            "-profile",
            project_relative(profile, project_dir),
            project_relative(source, project_dir),
            f"length={frames}",
            f"out={frames - 1}",
            "-filter",
            "qtblend",
            f"rect={animation}",
            "distort=0",
            "rotation=0",
            "compositing=0",
            "-consumer",
            f"avformat:{project_relative(output, project_dir)}",
            "vcodec=libx264",
            "crf=17",
            "preset=veryfast",
            "pix_fmt=yuv420p",
            "an=1",
            "real_time=-1",
        ],
        cwd=project_dir,
    )


def make_scene_clip(
    ffmpeg: Path,
    melt: Path | None,
    project_dir: Path,
    scene: dict[str, Any],
    duration: float,
    output: Path,
    width: int,
    height: int,
    fps: int,
    mlt_profile: Path,
    still_motion: dict[str, Any],
) -> None:
    visual = scene["visual"]
    source = project_file(project_dir, visual["path"])
    if not source.is_file():
        raise FileNotFoundError(f"シーン素材がありません: {source}")
    frames = max(1, round(duration * fps))
    is_image = visual.get("type", "image") == "image"
    motion = str(visual.get("motion", "none"))
    if is_image and motion != "none":
        if not melt:
            raise RuntimeError("静止画モーションに必要なMLT meltが見つかりません")
        make_mlt_still_clip(
            melt,
            project_dir,
            source,
            output,
            mlt_profile,
            frames,
            width,
            height,
            motion,
            still_motion,
        )
        return
    if not is_image and motion != "none":
        raise ValueError(f"動画素材には静止画モーションを指定できません: {scene['id']} motion={motion}")

    filter_value = visual_filter(width, height, fps)
    command: list[str | Path] = [ffmpeg, "-y"]
    if is_image:
        command += ["-loop", "1", "-i", source]
    else:
        command += ["-stream_loop", "-1"]
        if float(visual.get("source_start", 0)) > 0:
            command += ["-ss", str(visual["source_start"])]
        command += ["-i", source]
    command += [
        "-vf",
        filter_value,
        "-frames:v",
        str(frames),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "17",
        "-r",
        str(fps),
        "-pix_fmt",
        "yuv420p",
        output,
    ]
    run(command)


def scene_render_spec(
    project_dir: Path,
    scene: dict[str, Any],
    duration: float,
    width: int,
    height: int,
    fps: int,
    still_motion: dict[str, Any],
) -> dict[str, Any]:
    visual = scene["visual"]
    source = project_file(project_dir, visual["path"])
    is_image = visual.get("type", "image") == "image"
    motion = str(visual.get("motion", "none"))
    return {
        "scene_id": scene["id"],
        "source": visual["path"],
        "source_size": source.stat().st_size,
        "source_mtime_ns": source.stat().st_mtime_ns,
        "type": "image" if is_image else "video",
        "motion": motion,
        "engine": "mlt_qtblend_transform" if is_image and motion != "none" else "ffmpeg_scale_crop",
        "duration": round(duration, 6),
        "width": width,
        "height": height,
        "fps": fps,
        "still_motion": still_motion if is_image and motion != "none" else None,
    }


def ffmpeg_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")


def main() -> int:
    parser = argparse.ArgumentParser(description="FFmpegでシーンを組み、ASS字幕付き動画を作ります")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--quality", choices=("preview", "final"), default="preview")
    parser.add_argument("--reuse-scenes", action="store_true", help="既存の中間シーンクリップを明示的に再利用します")
    parser.add_argument("--no-subtitles", action="store_true")
    args = parser.parse_args()

    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpegが見つかりません")
    melt = find_executable("melt")
    project_dir = args.project_dir.resolve()
    project = read_json(project_dir / "project.json")
    timing = read_json(project_dir / "audio" / "timing.json")
    base_style = read_json(REPO_ROOT / "style.json")
    video = {**base_style["video"], **project.get("video", {})}
    audio_style = {**base_style["audio"], **project.get("audio", {})}
    still_motion = {
        **base_style.get("editing", {}).get("still_motion", {}),
        **project.get("editing", {}).get("still_motion", {}),
    }
    width, height, fps = int(video["width"]), int(video["height"]), int(video["fps"])

    work_dir = project_dir / "work"
    scene_dir = work_dir / "scenes"
    output_dir = project_dir / "output"
    scene_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    mlt_profile = work_dir / "mlt-profile"
    write_mlt_profile(mlt_profile, width, height, fps)
    timing_scenes = {scene["id"]: scene for scene in timing["scenes"]}
    manifest_path = work_dir / "scene-rendering.json"
    previous_manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    previous_specs = (
        {item["scene_id"]: item for item in previous_manifest.get("scenes", [])}
        if previous_manifest.get("renderer_version") == SCENE_RENDERER_VERSION
        else {}
    )
    scene_clips: list[Path] = []
    scene_specs: list[dict[str, Any]] = []
    for scene in project["scenes"]:
        scene_timing = timing_scenes[scene["id"]]
        duration = float(scene_timing["duration"])
        spec = scene_render_spec(project_dir, scene, duration, width, height, fps, still_motion)
        output = scene_dir / f"{scene['id']}.mp4"
        if not args.reuse_scenes or not output.exists() or previous_specs.get(scene["id"]) != spec:
            make_scene_clip(
                ffmpeg,
                melt,
                project_dir,
                scene,
                duration,
                output,
                width,
                height,
                fps,
                mlt_profile,
                still_motion,
            )
        scene_clips.append(output)
        scene_specs.append(spec)

    write_json(
        manifest_path,
        {
            "renderer_version": SCENE_RENDERER_VERSION,
            "scenes": scene_specs,
        },
    )

    concat_file = work_dir / "scenes.ffconcat"
    concat_lines = ["ffconcat version 1.0"]
    for clip in scene_clips:
        escaped = clip.resolve().as_posix().replace("'", "'\\''")
        concat_lines.append(f"file '{escaped}'")
    concat_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    visual_path = work_dir / "visual.mp4"
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", visual_path])

    narration_path = project_dir / "audio" / "narration.wav"
    subtitles_path = project_dir / "subtitles" / "subtitles.ass"
    total_duration = float(timing["total_duration"])
    output_path = output_dir / "preview.mp4" if args.quality == "preview" else final_output_path(project_dir, project)
    command: list[str | Path] = [ffmpeg, "-y", "-i", visual_path, "-i", narration_path]
    bgm_value = project.get("bgm")
    bgm_path = project_file(project_dir, bgm_value["path"]) if bgm_value else None
    if bgm_path:
        command += ["-stream_loop", "-1", "-i", bgm_path]
        fade_start = max(0.0, total_duration - 2.0)
        audio_filter = (
            f"[1:a]loudnorm=I={audio_style['narration_lufs']}:LRA=7:TP={audio_style['true_peak_db']}[voice];"
            f"[2:a]volume={audio_style['bgm_volume']},afade=t=out:st={fade_start:.3f}:d=2[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
            f"loudnorm=I={audio_style['final_lufs']}:LRA=7:TP={audio_style['true_peak_db']}[aout]"
        )
    else:
        audio_filter = f"[1:a]loudnorm=I={audio_style['final_lufs']}:LRA=7:TP={audio_style['true_peak_db']}[aout]"

    filters: list[str] = []
    if not args.no_subtitles:
        filters.append(f"subtitles=filename='{ffmpeg_filter_path(subtitles_path)}'")
    if args.quality == "preview":
        filters.append("scale=1280:720")
    filters.append("format=yuv420p")
    command += [
        "-filter_complex",
        audio_filter,
        "-vf",
        ",".join(filters),
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-t",
        f"{total_duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast" if args.quality == "preview" else "medium",
        "-crf",
        "27" if args.quality == "preview" else "18",
        "-c:a",
        "aac",
        "-b:a",
        "160k" if args.quality == "preview" else "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        output_path,
    ]
    run(command)
    print(
        json.dumps(
            {"output": str(output_path), "duration": media_duration(output_path), "rights_warning": RIGHTS_WARNING},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
