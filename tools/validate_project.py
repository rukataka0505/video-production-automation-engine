from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
from typing import Any

import opentimelineio as otio

from common import (
    ffprobe,
    final_output_path,
    find_executable,
    media_duration,
    project_file,
    read_json,
    run,
    scene_shots,
    shot_durations,
    write_json,
)


TIMING_TOLERANCE = 0.05
TIMELINE_TOLERANCE = 0.25
MOTION_VALUES = {"none", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down"}
THUMBNAIL_ASPECT_RATIO = 16 / 9
THUMBNAIL_ASPECT_TOLERANCE = 0.01
RIGHTS_WARNING = (
    "この動画は個人利用を前提として生成されています。Web上から取得した画像、動画、音声等が含まれる可能性があります。"
    "YouTube、SNS、Web等で公開、配布、商用利用する場合は、使用素材の著作権、ライセンス、利用条件を確認してください。"
)


def resolve_otio_target(target_url: str, timeline_path: Path) -> Path:
    if target_url.startswith("file:"):
        parsed = urlparse(target_url)
        path_text = unquote(parsed.path)
        if len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
            path_text = path_text[1:]
        return Path(path_text)
    path = Path(target_url)
    return path if path.is_absolute() else (timeline_path.parent / path).resolve()


def number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("有限値ではありません")
    return result


def close_enough(left: float, right: float, tolerance: float = TIMING_TOLERANCE) -> bool:
    return abs(left - right) <= tolerance


def normalize_text(value: Any) -> str:
    return str(value).replace("\r", "").replace("\n", "").replace(r"\N", "")


def parse_ass_time(value: str) -> float:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", value.strip())
    if not match:
        raise ValueError(f"ASS時刻が不正です: {value}")
    hours, minutes, seconds, centiseconds = (int(part) for part in match.groups())
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"ASS時刻が不正です: {value}")
    return hours * 3600 + minutes * 60 + seconds + centiseconds / 100


def read_ass_texts(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8-sig")
    if "[Events]" not in content:
        raise ValueError("ASSにEventsセクションがありません")
    texts: list[str] = []
    for line in content.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            raise ValueError("ASSのDialogue行を読み取れません")
        start = parse_ass_time(fields[1])
        end = parse_ass_time(fields[2])
        if end <= start:
            raise ValueError("ASSのDialogue時刻が逆転しています")
        if fields[8] == "double-outline-outer":
            continue
        texts.append(normalize_text(re.sub(r"\{[^}]*\}", "", fields[9])))
    return texts


def project_structure_errors(project: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(project, dict):
        return ["project.jsonのルートはオブジェクトである必要があります"]
    if not str(project.get("title", "")).strip():
        errors.append("project.jsonにtitleがありません")

    thumbnail = project.get("thumbnail")
    if not isinstance(thumbnail, dict):
        errors.append("project.jsonのthumbnailが空または不正です")
    else:
        for key in ("concept", "subject"):
            if not isinstance(thumbnail.get(key), str) or not thumbnail[key].strip():
                errors.append(f"project.jsonのthumbnail.{key}が空または不正です")
        thumbnail_text = thumbnail.get("text", "")
        if not isinstance(thumbnail_text, str):
            errors.append("project.jsonのthumbnail.textは文字列にしてください")
        youtube = project.get("youtube")
        youtube_title = youtube.get("title") if isinstance(youtube, dict) else None
        if thumbnail_text.strip() and normalize_text(thumbnail_text).casefold() == normalize_text(
            youtube_title or project.get("title", "")
        ).casefold():
            errors.append("サムネイル文言とYouTubeタイトルを同じ文言にしないでください")

    video = project.get("video", {})
    if video is not None and not isinstance(video, dict):
        errors.append("project.jsonのvideoはオブジェクトである必要があります")
    elif isinstance(video, dict):
        for key in ("width", "height", "fps"):
            if key not in video:
                continue
            try:
                if number(video[key]) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"project.jsonのvideo.{key}が不正です")

    scenes = project.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return errors + ["project.jsonのscenesが空または不正です"]

    scene_ids: set[str] = set()
    segment_ids: set[str] = set()
    for scene_index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            errors.append(f"scene[{scene_index}]がオブジェクトではありません")
            continue
        scene_id = str(scene.get("id", "")).strip()
        if not scene_id:
            errors.append(f"scene[{scene_index}]にidがありません")
        elif scene_id in scene_ids:
            errors.append(f"scene IDが重複しています: {scene_id}")
        else:
            scene_ids.add(scene_id)

        narration = scene.get("narration")
        if not isinstance(narration, list) or not narration:
            errors.append(f"{scene_id or f'scene[{scene_index}]'}のnarrationが空または不正です")
        else:
            for segment_index, segment in enumerate(narration, start=1):
                label = f"{scene_id or scene_index}/narration[{segment_index}]"
                if not isinstance(segment, dict):
                    errors.append(f"{label}がオブジェクトではありません")
                    continue
                segment_id = str(segment.get("id", "")).strip()
                text = segment.get("text")
                if not segment_id:
                    errors.append(f"{label}にidがありません")
                elif segment_id in segment_ids:
                    errors.append(f"narration segment IDが重複しています: {segment_id}")
                else:
                    segment_ids.add(segment_id)
                if not isinstance(text, str) or not text.strip():
                    errors.append(f"{label}に本文がありません")
                if "subtitle" in segment and normalize_text(segment["subtitle"]) != normalize_text(text):
                    errors.append(f"{label}の字幕本文がナレーションと一致しません")

        try:
            shots = scene_shots(scene)
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
            continue
        for shot_index, shot in enumerate(shots, start=1):
            label = f"{scene_id or scene_index}/shot[{shot_index}]"
            if not isinstance(shot, dict):
                errors.append(f"{label}がオブジェクトではありません")
                continue
            if not str(shot.get("path", "")).strip():
                errors.append(f"{label}にpathがありません")
            shot_type = str(shot.get("type", "image"))
            if shot_type not in {"image", "video"}:
                errors.append(f"{label}のtypeが不正です: {shot_type}")
            motion = str(shot.get("motion", "none"))
            if motion not in MOTION_VALUES:
                errors.append(f"{label}のmotionが不正です: {motion}")
            if shot_type == "video" and motion != "none":
                errors.append(f"{label}の動画素材に静止画motionが指定されています")
            if "source_start" in shot:
                try:
                    if number(shot["source_start"]) < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append(f"{label}のsource_startが不正です")
            if "duration_seconds" in shot:
                try:
                    if number(shot["duration_seconds"]) <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append(f"{label}のduration_secondsが不正です")

    bgm = project.get("bgm")
    if bgm is not None and (not isinstance(bgm, dict) or not str(bgm.get("path", "")).strip()):
        errors.append("project.jsonのbgm.pathが不正です")
    return errors


def flattened_narration(project: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"id": str(segment["id"]), "scene_id": str(scene["id"]), "text": str(segment["text"])}
        for scene in project["scenes"]
        for segment in scene["narration"]
    ]


def validate_timing(
    project_dir: Path,
    project: dict[str, Any],
    timing: Any,
    checks: dict[str, object],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(timing, dict):
        errors.append("audio/timing.jsonのルートが不正です")
        return {}
    segments = timing.get("segments")
    scenes = timing.get("scenes")
    if not isinstance(segments, list) or not isinstance(scenes, list):
        errors.append("audio/timing.jsonのsegmentsまたはscenesが不正です")
        return {}

    expected = flattened_narration(project)
    checks["timing_segment_count"] = len(segments)
    if [item.get("id") for item in segments if isinstance(item, dict)] != [item["id"] for item in expected]:
        errors.append("audio/timing.jsonのsegment IDまたは順序がproject.jsonと一致しません")
    if [item.get("scene_id") for item in segments if isinstance(item, dict)] != [item["scene_id"] for item in expected]:
        errors.append("audio/timing.jsonのscene_idまたは順序がproject.jsonと一致しません")
    if [normalize_text(item.get("text", "")) for item in segments if isinstance(item, dict)] != [
        normalize_text(item["text"]) for item in expected
    ]:
        errors.append("audio/timing.jsonの本文がproject.jsonと一致しません")

    segment_values_ok = len(segments) == len(expected) and all(isinstance(item, dict) for item in segments)
    previous_end = 0.0
    previous_hold = 0.0
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            errors.append(f"audio/timing.jsonのsegment[{index}]が不正です")
            segment_values_ok = False
            continue
        label = str(segment.get("id", f"segment[{index}]"))
        try:
            start = number(segment["start"])
            end = number(segment["end"])
            audio_duration = number(segment["audio_duration"])
            hold_after = number(segment.get("hold_after", 0))
            if start < 0 or end <= start or audio_duration <= 0 or hold_after < 0:
                raise ValueError
            if not close_enough(end - start, audio_duration):
                raise ValueError
            if index == 1 and not close_enough(start, 0):
                raise ValueError
            if index > 1 and not close_enough(start, previous_end + previous_hold):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            errors.append(f"audio/timing.jsonの実測タイミングが不正です: {label}")
            segment_values_ok = False
            continue
        previous_end = end
        previous_hold = hold_after

        wav_value = str(segment.get("wav", "")).strip()
        if not wav_value:
            errors.append(f"audio/timing.jsonにWAV参照がありません: {label}")
            continue
        try:
            wav_path = project_file(project_dir, wav_value)
        except ValueError as exc:
            errors.append(f"audio/timing.jsonのWAV参照が不正です: {label}: {exc}")
            continue
        if not wav_path.is_file():
            errors.append(f"audio/timing.jsonが参照するWAVがありません: {wav_value}")
            continue
        try:
            actual_duration = media_duration(wav_path)
            if not close_enough(actual_duration, audio_duration):
                errors.append(f"WAV実尺がaudio/timing.jsonと一致しません: {wav_value}")
        except Exception as exc:
            errors.append(f"WAVを読み取れません: {wav_value}: {exc}")

    try:
        total_duration = number(timing["total_duration"])
        if total_duration <= 0 or not segment_values_ok or not close_enough(total_duration, previous_end + previous_hold):
            raise ValueError
        checks["timing_total_duration"] = total_duration
    except (KeyError, TypeError, ValueError):
        errors.append("audio/timing.jsonのtotal_durationが実測タイミングと一致しません")

    timing_scene_map: dict[str, dict[str, Any]] = {}
    expected_scene_ids = [str(scene["id"]) for scene in project["scenes"]]
    actual_scene_ids = [str(scene.get("id", "")) for scene in scenes if isinstance(scene, dict)]
    if actual_scene_ids != expected_scene_ids:
        errors.append("audio/timing.jsonのscene IDまたは順序がproject.jsonと一致しません")
        return {}

    for project_scene, timing_scene in zip(project["scenes"], scenes, strict=True):
        if not isinstance(timing_scene, dict):
            errors.append(f"audio/timing.jsonのsceneが不正です: {project_scene['id']}")
            continue
        scene_segments = [item for item in segments if isinstance(item, dict) and item.get("scene_id") == project_scene["id"]]
        if not scene_segments:
            errors.append(f"audio/timing.jsonにsceneのsegmentがありません: {project_scene['id']}")
            continue
        try:
            start = number(timing_scene["start"])
            end = number(timing_scene["end"])
            duration = number(timing_scene["duration"])
            expected_start = number(scene_segments[0]["start"])
            expected_end = number(scene_segments[-1]["end"]) + number(scene_segments[-1].get("hold_after", 0))
            if duration <= 0 or not close_enough(start, expected_start) or not close_enough(end, expected_end):
                raise ValueError
            if not close_enough(duration, end - start):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            errors.append(f"audio/timing.jsonのscene実測タイミングが不正です: {project_scene['id']}")
            continue
        timing_scene_map[str(project_scene["id"])] = timing_scene
    return timing_scene_map


def validate_project_media(
    project_dir: Path,
    project: dict[str, Any],
    timing_scenes: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    for scene in project["scenes"]:
        scene_id = str(scene["id"])
        if scene_id not in timing_scenes:
            continue
        try:
            shots = scene_shots(scene)
            durations = shot_durations(scene, number(timing_scenes[scene_id]["duration"]))
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"project.jsonのshot構成を生成に使えません: {scene_id}: {exc}")
            continue
        for index, (shot, required_duration) in enumerate(zip(shots, durations, strict=True), start=1):
            label = f"{scene_id}/shot[{index}]"
            try:
                path = project_file(project_dir, str(shot["path"]))
            except (KeyError, ValueError) as exc:
                errors.append(f"必須shot素材の参照が不正です: {label}: {exc}")
                continue
            if not path.is_file():
                errors.append(f"必須shot素材がありません: {label}: {shot['path']}")
                continue
            if shot.get("type", "image") != "video":
                continue
            try:
                source_duration = media_duration(path)
                source_start = number(shot.get("source_start", 0))
            except Exception as exc:
                errors.append(f"動画shot素材を読み取れません: {label}: {exc}")
                continue
            if source_start < 0 or source_start >= source_duration:
                errors.append(f"動画shotのsource_startが素材範囲外です: {label}")
            elif required_duration > source_duration - source_start + 0.001:
                errors.append(
                    f"動画shotに必要な尺が素材の残り尺を超えています: {label} "
                    f"required={required_duration:.3f}s available={source_duration - source_start:.3f}s"
                )

    if project.get("bgm"):
        try:
            bgm_path = project_file(project_dir, str(project["bgm"]["path"]))
            if not bgm_path.is_file():
                errors.append(f"BGM素材がありません: {project['bgm']['path']}")
        except (KeyError, ValueError) as exc:
            errors.append(f"BGM素材の参照が不正です: {exc}")


def stream_fps(stream: dict[str, Any]) -> float | None:
    value = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    if not value:
        return None
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return None


def validate_final_video(
    final_path: Path,
    project: dict[str, Any],
    timing: dict[str, Any],
    checks: dict[str, object],
    errors: list[str],
) -> None:
    checks["final_exists"] = final_path.is_file()
    if not final_path.is_file():
        errors.append(f"完成動画がありません: {final_path}")
        return
    try:
        media = ffprobe(final_path)
        duration = number(media.get("format", {}).get("duration"))
    except Exception as exc:
        errors.append(f"完成動画を読み取れません: {exc}")
        return

    video_streams = [stream for stream in media.get("streams", []) if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in media.get("streams", []) if stream.get("codec_type") == "audio"]
    checks["final_has_video"] = bool(video_streams)
    checks["final_has_audio"] = bool(audio_streams)
    checks["final_duration"] = duration
    if not video_streams:
        errors.append("完成動画に映像ストリームがありません")
    if not audio_streams:
        errors.append("完成動画に音声ストリームがありません")
    try:
        timing_duration = number(timing["total_duration"])
        checks["final_duration_matches_timing"] = close_enough(duration, timing_duration, TIMELINE_TOLERANCE)
        if not checks["final_duration_matches_timing"]:
            errors.append("完成動画の尺がaudio/timing.jsonと重大に不一致です")
    except (KeyError, TypeError, ValueError):
        pass

    if video_streams:
        stream = video_streams[0]
        explicit_video = project.get("video", {})
        if isinstance(explicit_video, dict):
            if "width" in explicit_video and int(stream.get("width", 0)) != int(explicit_video["width"]):
                errors.append("完成動画の幅がproject.jsonの納品仕様と一致しません")
            if "height" in explicit_video and int(stream.get("height", 0)) != int(explicit_video["height"]):
                errors.append("完成動画の高さがproject.jsonの納品仕様と一致しません")
            if "fps" in explicit_video:
                actual_fps = stream_fps(stream)
                if actual_fps is None or not close_enough(actual_fps, number(explicit_video["fps"]), 0.01):
                    errors.append("完成動画のfpsがproject.jsonの納品仕様と一致しません")

    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        errors.append("完成動画の全体デコード検査に必要なffmpegが見つかりません")
        return
    try:
        run([ffmpeg, "-xerror", "-v", "error", "-i", final_path, "-f", "null", "-"], capture=True)
        checks["full_decode"] = "passed"
    except Exception as exc:
        checks["full_decode"] = "failed"
        errors.append(f"完成動画を最後までデコードできません: {exc}")


def validate_subtitles(
    ass_path: Path,
    project: dict[str, Any],
    timing: dict[str, Any],
    checks: dict[str, object],
    errors: list[str],
) -> None:
    checks["subtitles_exist"] = ass_path.is_file()
    if not ass_path.is_file():
        errors.append(f"ASS字幕がありません: {ass_path}")
        return
    try:
        ass_texts = read_ass_texts(ass_path)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"ASS字幕を読み取れません: {exc}")
        return

    project_texts = [normalize_text(item["text"]) for item in flattened_narration(project)]
    timing_segments = timing.get("segments", []) if isinstance(timing, dict) else []
    checks["subtitle_cue_count"] = len(ass_texts)
    checks["timing_segment_count"] = len(timing_segments) if isinstance(timing_segments, list) else 0
    if len(ass_texts) != checks["timing_segment_count"]:
        errors.append("ASS字幕数と音声セグメント数が一致しません")
    if ass_texts != project_texts:
        errors.append("ASS字幕本文とproject.jsonのナレーション本文が一致しません")


def validate_otio(
    otio_path: Path,
    project: dict[str, Any],
    timing: dict[str, Any],
    checks: dict[str, object],
    errors: list[str],
) -> None:
    checks["otio_exists"] = otio_path.is_file()
    if not otio_path.is_file():
        errors.append(f"OTIOがありません: {otio_path}")
        return
    try:
        timeline = otio.adapters.read_from_file(str(otio_path))
    except Exception as exc:
        errors.append(f"OTIOを読み取れません: {exc}")
        return

    tracks_by_name = {track.name: track for track in timeline.tracks}
    required = {"V1 Visuals": otio.schema.TrackKind.Video, "A1 Narration": otio.schema.TrackKind.Audio}
    if project.get("bgm"):
        required["A2 BGM"] = otio.schema.TrackKind.Audio
    checks["otio_tracks"] = list(tracks_by_name)
    for name, kind in required.items():
        track = tracks_by_name.get(name)
        if track is None or track.kind != kind:
            errors.append(f"OTIOに必須トラックがありません: {name}")

    try:
        total_duration = number(timing["total_duration"])
    except (KeyError, TypeError, ValueError):
        total_duration = 0.0
    if total_duration > 0:
        try:
            actual_duration = timeline.duration().to_seconds()
            checks["otio_duration"] = actual_duration
            if not close_enough(actual_duration, total_duration, TIMELINE_TOLERANCE):
                errors.append("OTIOの全体尺がaudio/timing.jsonと重大に不一致です")
        except Exception as exc:
            errors.append(f"OTIOの全体尺を読み取れません: {exc}")
        for name in required:
            track = tracks_by_name.get(name)
            if track is None:
                continue
            try:
                track_duration = track.duration().to_seconds()
                if not close_enough(track_duration, total_duration, TIMELINE_TOLERANCE):
                    errors.append(f"OTIOの{name}尺がaudio/timing.jsonと重大に不一致です")
            except Exception as exc:
                errors.append(f"OTIOの{name}尺を読み取れません: {exc}")

    missing_media: list[str] = []
    range_errors: list[str] = []
    for track in timeline.tracks:
        for clip in track.find_clips():
            label = f"{track.name}/{clip.name}"
            reference = clip.media_reference
            target_url = str(getattr(reference, "target_url", "") or "")
            if not target_url or not resolve_otio_target(target_url, otio_path).is_file():
                missing_media.append(label)
            available = getattr(reference, "available_range", None)
            source = clip.source_range
            if available is None or source is None:
                range_errors.append(label)
                continue
            try:
                available_start = available.start_time.to_seconds()
                available_end = available.end_time_exclusive().to_seconds()
                source_start = source.start_time.to_seconds()
                source_end = source.end_time_exclusive().to_seconds()
                if source_start < available_start - 0.001 or source_end > available_end + 0.001:
                    range_errors.append(label)
            except Exception:
                range_errors.append(label)
    checks["otio_missing_media"] = missing_media
    checks["otio_media_range_errors"] = range_errors
    if missing_media:
        errors.append(f"OTIOが参照する必須素材がありません: {', '.join(missing_media)}")
    if range_errors:
        errors.append(f"OTIOに素材尺外参照があります: {', '.join(range_errors)}")


def validate_native_kdenlive(project_dir: Path, project: dict[str, Any], checks: dict[str, object], errors: list[str]) -> None:
    required = bool(project.get("deliverables", {}).get("require_native_kdenlive"))
    checks["native_kdenlive_required"] = required
    if not required:
        return
    path = project_dir / "timeline" / "edit.kdenlive"
    if not path.is_file():
        errors.append("明示的に要求されたKdenliveネイティブプロジェクトがありません")
        return
    try:
        ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        errors.append(f"Kdenliveネイティブプロジェクトを読み取れません: {exc}")


def validate_thumbnail(path: Path, checks: dict[str, object], errors: list[str]) -> None:
    checks["thumbnail_exists"] = path.is_file()
    if not path.is_file():
        errors.append(f"サムネイルがありません: {path}")
        return
    try:
        with path.open("rb") as source:
            header = source.read(3)
    except OSError as exc:
        errors.append(f"サムネイルを読み取れません: {exc}")
        return
    checks["thumbnail_is_jpeg"] = header == b"\xff\xd8\xff"
    if not checks["thumbnail_is_jpeg"]:
        errors.append("output/thumbnail.jpgが有効なJPEGではありません")
        return
    try:
        info = ffprobe(path)
        stream = next(item for item in info.get("streams", []) if item.get("codec_type") == "video")
        width = int(stream["width"])
        height = int(stream["height"])
    except Exception as exc:
        errors.append(f"サムネイル画像を解析できません: {exc}")
        return
    checks["thumbnail_dimensions"] = {"width": width, "height": height}
    if width < 640 or height <= 0:
        errors.append("サムネイルは幅640px以上にしてください")
    if height > 0 and abs(width / height - THUMBNAIL_ASPECT_RATIO) > THUMBNAIL_ASPECT_TOLERANCE:
        errors.append("サムネイルは16:9で作成してください")


def finish_result(project_dir: Path, checks: dict[str, object], errors: list[str], warnings: list[str]) -> dict[str, object]:
    result = {
        **checks,
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "rights_warning": RIGHTS_WARNING,
    }
    if project_dir.is_dir():
        write_json(project_dir / "qa" / "validation.json", result)
    return result


def validate_project(project_dir: Path) -> dict[str, object]:
    project_dir = project_dir.resolve()
    checks: dict[str, object] = {}
    errors: list[str] = []
    warnings: list[str] = []

    project_path = project_dir / "project.json"
    checks["project_exists"] = project_path.is_file()
    if not project_path.is_file():
        errors.append(f"project.jsonがありません: {project_path}")
        return finish_result(project_dir, checks, errors, warnings)
    try:
        project = read_json(project_path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"project.jsonを読み取れません: {exc}")
        return finish_result(project_dir, checks, errors, warnings)

    structure_errors = project_structure_errors(project)
    if structure_errors:
        errors.extend(structure_errors)
        return finish_result(project_dir, checks, errors, warnings)

    try:
        final_path = final_output_path(project_dir, project)
    except (TypeError, ValueError) as exc:
        errors.append(f"project.jsonの納品ファイル名が不正です: {exc}")
        return finish_result(project_dir, checks, errors, warnings)
    checks["final_filename"] = final_path.name

    timing_path = project_dir / "audio" / "timing.json"
    checks["timing_exists"] = timing_path.is_file()
    if not timing_path.is_file():
        errors.append(f"audio/timing.jsonがありません: {timing_path}")
        timing: dict[str, Any] = {}
        timing_scenes: dict[str, dict[str, Any]] = {}
    else:
        try:
            timing = read_json(timing_path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"audio/timing.jsonを読み取れません: {exc}")
            timing = {}
            timing_scenes = {}
        else:
            timing_scenes = validate_timing(project_dir, project, timing, checks, errors)

    validate_project_media(project_dir, project, timing_scenes, errors)
    validate_final_video(final_path, project, timing, checks, errors)
    validate_subtitles(project_dir / "subtitles" / "subtitles.ass", project, timing, checks, errors)
    validate_otio(project_dir / "timeline" / "edit.otio", project, timing, checks, errors)
    validate_native_kdenlive(project_dir, project, checks, errors)
    validate_thumbnail(project_dir / "output" / "thumbnail.jpg", checks, errors)
    return finish_result(project_dir, checks, errors, warnings)


def main() -> int:
    parser = argparse.ArgumentParser(description="完成動画と必須編集成果物が実際に利用できることを検証します")
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    result = validate_project(args.project_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
