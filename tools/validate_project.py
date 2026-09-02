from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

import opentimelineio as otio

from common import ffprobe, final_output_path, media_duration, read_json, write_json


def resolve_otio_target(target_url: str, timeline_path: Path) -> Path:
    if target_url.startswith("file:"):
        parsed = urlparse(target_url)
        path_text = unquote(parsed.path)
        if len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
            path_text = path_text[1:]
        return Path(path_text)
    path = Path(target_url)
    return path if path.is_absolute() else (timeline_path.parent / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="動画プロジェクトの完成条件を検証します")
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    project_dir = args.project_dir.resolve()
    project = read_json(project_dir / "project.json")
    timing = read_json(project_dir / "audio" / "timing.json")
    sources = read_json(project_dir / "sources.json")
    final_path = final_output_path(project_dir, project)
    ass_path = project_dir / "subtitles" / "subtitles.ass"
    otio_path = project_dir / "timeline" / "edit.otio"
    qa_dir = project_dir / "qa"

    checks: dict[str, object] = {}
    checks["final_filename"] = final_path.name
    errors: list[str] = []
    for label, path in {
        "final": final_path,
        "subtitles": ass_path,
        "timeline": otio_path,
        "research": project_dir / "research.md",
        "brief": project_dir / "brief.md",
        "sources": project_dir / "sources.json",
    }.items():
        checks[f"{label}_exists"] = path.is_file()
        if not path.is_file():
            errors.append(f"不足ファイル: {path}")

    if final_path.is_file():
        media = ffprobe(final_path)
        video_streams = [stream for stream in media.get("streams", []) if stream.get("codec_type") == "video"]
        audio_streams = [stream for stream in media.get("streams", []) if stream.get("codec_type") == "audio"]
        duration = float(media["format"]["duration"])
        checks["final_duration"] = duration
        checks["duration_matches_timing"] = abs(duration - float(timing["total_duration"])) < 0.25
        if not checks["duration_matches_timing"]:
            errors.append("完成動画の尺がVOICEVOX実測タイミングと一致しません")
        target_duration = project.get("video", {}).get("target_duration_seconds")
        if target_duration:
            checks["duration_in_target_range"] = float(target_duration["min"]) <= duration <= float(target_duration["max"])
            if not checks["duration_in_target_range"]:
                errors.append("完成動画の尺が指定範囲外です")
        checks["has_video"] = bool(video_streams)
        checks["has_audio"] = bool(audio_streams)
        if not video_streams or not audio_streams:
            errors.append("完成動画に映像または音声ストリームがありません")
        if video_streams:
            checks["resolution"] = f"{video_streams[0].get('width')}x{video_streams[0].get('height')}"
            checks["resolution_matches_project"] = (
                int(video_streams[0].get("width", 0)) == int(project["video"]["width"])
                and int(video_streams[0].get("height", 0)) == int(project["video"]["height"])
            )
            if not checks["resolution_matches_project"]:
                errors.append("完成動画の解像度がproject.jsonと一致しません")
        if audio_streams:
            checks["audio_sample_rate"] = int(audio_streams[0].get("sample_rate", 0))
            if checks["audio_sample_rate"] != 48000:
                errors.append("完成動画の音声サンプルレートが48kHzではありません")

    if otio_path.is_file():
        timeline = otio.adapters.read_from_file(str(otio_path))
        checks["otio_tracks"] = [track.name for track in timeline.tracks]
        checks["otio_readable"] = True
        required_tracks = {"V1 Visuals", "A1 Narration", "A2 BGM"}
        checks["otio_required_tracks_present"] = required_tracks.issubset(set(checks["otio_tracks"]))
        if not checks["otio_required_tracks_present"]:
            errors.append("OTIOに映像・ナレーション・BGMの必須トラックが揃っていません")
        checks["otio_duration"] = timeline.duration().to_seconds()
        checks["otio_duration_matches_timing"] = abs(checks["otio_duration"] - float(timing["total_duration"])) < 0.25
        if not checks["otio_duration_matches_timing"]:
            errors.append("OTIOタイムラインの尺がVOICEVOX実測タイミングと一致しません")
        range_errors: list[str] = []
        missing_media: list[str] = []
        clip_count = 0
        for track in timeline.tracks:
            for clip in track.find_clips():
                clip_count += 1
                available = clip.media_reference.available_range
                source = clip.source_range
                target_url = getattr(clip.media_reference, "target_url", "")
                if target_url and not resolve_otio_target(target_url, otio_path).is_file():
                    missing_media.append(f"{track.name}/{clip.name}")
                if available is None or source is None:
                    continue
                available_start = available.start_time.to_seconds()
                available_end = available.end_time_exclusive().to_seconds()
                source_start = source.start_time.to_seconds()
                source_end = source.end_time_exclusive().to_seconds()
                if source_start < available_start - 0.001 or source_end > available_end + 0.001:
                    range_errors.append(f"{track.name}/{clip.name}")
        checks["otio_clip_count"] = clip_count
        checks["otio_media_range_errors"] = range_errors
        checks["otio_missing_media"] = missing_media
        if range_errors:
            errors.append(f"OTIOで素材尺を越えるクリップがあります: {', '.join(range_errors)}")
        if missing_media:
            errors.append(f"OTIOが参照する素材が見つかりません: {', '.join(missing_media)}")
        marker_ids = {marker.metadata.get("scene_id") for marker in timeline.tracks.markers}
        project_scene_ids = {scene["id"] for scene in project.get("scenes", [])}
        checks["otio_scene_markers_complete"] = marker_ids == project_scene_ids
        checks["otio_scene_marker_count"] = len(marker_ids)
        if not checks["otio_scene_markers_complete"]:
            errors.append("OTIOのシーンマーカーがproject.jsonと一致しません")
        subtitle_url = timeline.metadata.get("project", {}).get("subtitles", "")
        checks["otio_subtitle_reference_exists"] = bool(subtitle_url) and resolve_otio_target(subtitle_url, otio_path).is_file()
        if not checks["otio_subtitle_reference_exists"]:
            errors.append("OTIOメタデータの字幕参照が見つかりません")

    native_path = project_dir / "timeline" / "edit.kdenlive"
    native_ass_path = Path(f"{native_path}.ass")
    native_required = bool(project.get("deliverables", {}).get("require_native_kdenlive"))
    checks["native_kdenlive_required"] = native_required
    checks["native_kdenlive_exists"] = native_path.is_file()
    if native_required and not native_path.is_file():
        errors.append("Kdenlive自身で保存したネイティブ編集プロジェクトがありません")
    if native_path.is_file():
        try:
            native_root = ET.parse(native_path).getroot()
            profile = native_root.find("profile")
            checks["native_kdenlive_profile"] = {
                "width": int(profile.attrib.get("width", 0)) if profile is not None else 0,
                "height": int(profile.attrib.get("height", 0)) if profile is not None else 0,
                "fps_num": int(profile.attrib.get("frame_rate_num", 0)) if profile is not None else 0,
                "fps_den": int(profile.attrib.get("frame_rate_den", 1)) if profile is not None else 1,
            }
            native_profile = checks["native_kdenlive_profile"]
            checks["native_kdenlive_profile_matches"] = (
                native_profile["width"] == int(project["video"]["width"])
                and native_profile["height"] == int(project["video"]["height"])
                and native_profile["fps_num"] / native_profile["fps_den"] == float(project["video"]["fps"])
            )
            if not checks["native_kdenlive_profile_matches"]:
                errors.append("Kdenliveネイティブプロジェクトの映像プロファイルが不一致です")

            native_track_names = {
                node.text or "" for node in native_root.findall(".//property[@name='kdenlive:track_name']")
            }
            checks["native_kdenlive_tracks"] = sorted(native_track_names)
            checks["native_kdenlive_required_tracks_present"] = {
                "V1 Visuals", "A1 Narration", "A2 BGM"
            }.issubset(native_track_names)
            if not checks["native_kdenlive_required_tracks_present"]:
                errors.append("Kdenliveネイティブプロジェクトに必須トラックが揃っていません")

            resource_values = [
                (node.text or "").removeprefix("qimage:")
                for node in native_root.findall(".//property[@name='resource']")
                if (node.text or "") not in {"", "black"}
            ]
            native_missing_resources: list[str] = []
            resolved_resources: set[Path] = set()
            for resource in resource_values:
                resource_path = Path(resource)
                resolved = resource_path if resource_path.is_absolute() else (native_path.parent / resource_path).resolve()
                resolved_resources.add(resolved)
                if not resolved.is_file():
                    native_missing_resources.append(resource)
            checks["native_kdenlive_resource_count"] = len(resource_values)
            checks["native_kdenlive_missing_resources"] = native_missing_resources
            if native_missing_resources:
                errors.append(f"Kdenliveネイティブプロジェクトの参照素材が不足: {', '.join(native_missing_resources)}")

            expected_visuals = {
                (project_dir / Path(scene["visual"]["path"])).resolve() for scene in project.get("scenes", [])
            }
            missing_native_visuals = sorted(str(path) for path in expected_visuals - resolved_resources)
            checks["native_kdenlive_missing_scene_visuals"] = missing_native_visuals
            if missing_native_visuals:
                errors.append("Kdenliveネイティブプロジェクトに未配置のシーン素材があります")

            subtitle_metadata = native_root.find(".//property[@name='kdenlive:sequenceproperties.subtitlesList']")
            checks["native_kdenlive_subtitle_metadata"] = subtitle_metadata is not None and bool((subtitle_metadata.text or "").strip())
            checks["native_kdenlive_ass_exists"] = native_ass_path.is_file()
            native_cue_count = (
                sum(1 for line in native_ass_path.read_text(encoding="utf-8-sig").splitlines() if line.startswith("Dialogue:"))
                if native_ass_path.is_file()
                else 0
            )
            checks["native_kdenlive_subtitle_cue_count"] = native_cue_count
            if not checks["native_kdenlive_subtitle_metadata"] or native_cue_count != len(timing.get("segments", [])):
                errors.append("Kdenliveネイティブプロジェクトの字幕が不完全です")
        except (ET.ParseError, OSError, ValueError, ZeroDivisionError) as exc:
            checks["native_kdenlive_parse_error"] = str(exc)
            errors.append(f"Kdenliveネイティブプロジェクトを検証できません: {exc}")

    source_ids = {source.get("id") for source in sources if source.get("id")}
    used_ids = {scene.get("visual", {}).get("source_id") for scene in project["scenes"] if scene.get("visual", {}).get("source_id")}
    if project.get("bgm", {}).get("source_id"):
        used_ids.add(project["bgm"]["source_id"])
    missing_source_ids = sorted(used_ids - source_ids)
    checks["source_entries"] = len(sources)
    checks["missing_source_ids"] = missing_source_ids
    if missing_source_ids:
        errors.append(f"出典未登録: {', '.join(missing_source_ids)}")
    for source in sources:
        if not source.get("url") or not source.get("provider"):
            errors.append(f"出典URLまたは提供元が不足: {source.get('id', '(no id)')}")
        local_path = source.get("local_path")
        if local_path:
            resolved = project_dir / Path(local_path)
            if not resolved.is_file():
                errors.append(f"出典登録されたローカル素材が見つかりません: {local_path}")

    cue_count = sum(1 for line in ass_path.read_text(encoding="utf-8-sig").splitlines() if line.startswith("Dialogue:")) if ass_path.is_file() else 0
    checks["subtitle_cue_count"] = cue_count
    checks["timing_segment_count"] = len(timing.get("segments", []))
    if cue_count != checks["timing_segment_count"]:
        errors.append("字幕数とVOICEVOX音声セグメント数が一致しません")

    timing_scenes = {scene["id"]: scene for scene in timing.get("scenes", [])}
    work_scene_errors: list[str] = []
    for scene in project.get("scenes", []):
        scene_id = scene["id"]
        work_scene = project_dir / "work" / "scenes" / f"{scene_id}.mp4"
        if not work_scene.is_file():
            work_scene_errors.append(f"{scene_id}:missing")
            continue
        expected = float(timing_scenes[scene_id]["duration"])
        actual = media_duration(work_scene)
        if abs(actual - expected) > 0.075:
            work_scene_errors.append(f"{scene_id}:{actual:.3f}!={expected:.3f}")
    checks["work_scene_duration_errors"] = work_scene_errors
    if work_scene_errors:
        errors.append(f"中間シーンクリップの尺が不正です: {', '.join(work_scene_errors)}")

    rendering_manifest_path = project_dir / "work" / "scene-rendering.json"
    checks["scene_rendering_manifest_exists"] = rendering_manifest_path.is_file()
    if rendering_manifest_path.is_file():
        rendering_manifest = read_json(rendering_manifest_path)
        checks["scene_renderer_version"] = rendering_manifest.get("renderer_version")
        rendering_scenes = {item.get("scene_id"): item for item in rendering_manifest.get("scenes", [])}
        motion_engine_errors: list[str] = []
        for scene in project.get("scenes", []):
            visual = scene.get("visual", {})
            if visual.get("type", "image") != "image" or visual.get("motion", "none") == "none":
                continue
            rendered = rendering_scenes.get(scene["id"], {})
            if rendered.get("engine") != "mlt_qtblend_transform":
                motion_engine_errors.append(scene["id"])
        checks["still_motion_engine_errors"] = motion_engine_errors
        if motion_engine_errors:
            errors.append(
                "静止画モーションがMLT Transformでレンダーされていません: " + ", ".join(motion_engine_errors)
            )
    else:
        errors.append("中間シーンのレンダー方式記録がありません。全シーンを再レンダーしてください")

    qa_frames = sorted(qa_dir.glob("frame-*.png"))
    scene_qa_frames = sorted(qa_dir.glob("scene-*.png"))
    checks["qa_frame_count"] = len(qa_frames)
    checks["qa_contact_sheet"] = (qa_dir / "contact-sheet.jpg").is_file()
    checks["scene_qa_frame_count"] = len(scene_qa_frames)
    checks["scene_qa_contact_sheet"] = (qa_dir / "scene-contact-sheet.jpg").is_file()
    all_scene_qa_required = bool(project.get("deliverables", {}).get("require_all_scene_qa"))
    checks["all_scene_qa_required"] = all_scene_qa_required
    checks["all_scenes_have_qa_frame"] = len(scene_qa_frames) == len(project.get("scenes", []))
    if len(qa_frames) < 4:
        errors.append("QA代表フレームが4枚未満です")
    if all_scene_qa_required and (not checks["all_scenes_have_qa_frame"] or not checks["scene_qa_contact_sheet"]):
        errors.append("全シーンQAのフレームまたはコンタクトシートが不足しています")
    checks["passed"] = not errors
    checks["errors"] = errors
    checks["rights_warning"] = (
        "この動画は個人利用を前提として生成されています。Web上から取得した画像・動画・音声等が含まれる可能性があります。"
        "YouTube、SNS、Web等で公開・配布・商用利用する場合は、使用素材の著作権・ライセンス・利用条件を確認してください。"
    )
    write_json(qa_dir / "validation.json", checks)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
