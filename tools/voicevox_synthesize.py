from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Any

from common import REPO_ROOT, media_duration, read_json, write_json


MOUTH_STATES = {"a", "i", "u", "e", "o", "n", "closed"}


def post_json(url: str, payload: dict[str, Any] | None = None) -> tuple[bytes, str]:
    data = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read(), response.headers.get_content_type()


def wav_spec(path: Path) -> tuple[wave._wave_params, bytes, float]:
    with wave.open(str(path), "rb") as wav:
        params = wav.getparams()
        frames = wav.readframes(params.nframes)
        duration = params.nframes / params.framerate
    return params, frames, duration


def audio_query_mouth_timing(query: dict[str, Any], audio_duration: float) -> list[dict[str, Any]]:
    """Convert VOICEVOX mora timing into relative mouth-shape intervals."""
    speed_scale = max(0.01, float(query.get("speedScale", 1.0)))
    phases: list[tuple[str, float]] = []

    def append(state: str, duration: float) -> None:
        duration = max(0.0, duration)
        state = state if state in MOUTH_STATES else "closed"
        if duration <= 0:
            return
        if phases and phases[-1][0] == state:
            phases[-1] = (state, phases[-1][1] + duration)
        else:
            phases.append((state, duration))

    append("closed", float(query.get("prePhonemeLength", 0.0)))
    for phrase in query.get("accent_phrases", []):
        for mora in phrase.get("moras", []):
            vowel = str(mora.get("vowel", "")).lower()
            state = vowel if vowel in MOUTH_STATES - {"closed"} else "closed"
            consonant_length = float(mora.get("consonant_length") or 0.0)
            vowel_length = float(mora.get("vowel_length") or 0.0)
            append(state, (consonant_length + vowel_length) / speed_scale)
        pause = phrase.get("pause_mora")
        if pause:
            consonant_length = float(pause.get("consonant_length") or 0.0)
            vowel_length = float(pause.get("vowel_length") or 0.0)
            append("closed", (consonant_length + vowel_length) / speed_scale)
    append("closed", float(query.get("postPhonemeLength", 0.0)))

    nominal_duration = sum(duration for _, duration in phases)
    if nominal_duration <= 0 or audio_duration <= 0:
        return [{"state": "closed", "start": 0.0, "end": max(0.0, audio_duration)}]

    scale = audio_duration / nominal_duration
    cursor = 0.0
    timing: list[dict[str, Any]] = []
    for index, (state, duration) in enumerate(phases):
        start = cursor
        cursor = audio_duration if index == len(phases) - 1 else cursor + duration * scale
        timing.append({"state": state, "start": start, "end": cursor})
    return timing


def main() -> int:
    parser = argparse.ArgumentParser(description="project.jsonからVOICEVOXナレーションと実測タイミングを作ります")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    project = read_json(project_dir / "project.json")
    style = read_json(REPO_ROOT / "style.json")
    project_voicevox = project.get("voicevox", {})
    settings = {**style["voicevox"], **project_voicevox}
    speaker = int(settings.pop("speaker"))
    speaker_map = {
        **style["voicevox"].get("speakers", {}),
        **project_voicevox.get("speakers", {}),
    }
    settings.pop("speakers", None)
    settings.pop("speaker_label", None)
    default_gap = float(style["audio"]["default_segment_gap_seconds"])
    base_url = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")

    with urllib.request.urlopen(f"{base_url}/version", timeout=3) as response:
        engine_version = response.read().decode("utf-8").strip('"')

    segment_dir = project_dir / "audio" / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    segment_records: list[dict[str, Any]] = []

    for scene in project["scenes"]:
        for segment in scene["narration"]:
            segment_id = segment["id"]
            speaker_key = segment.get("speaker_key", "default")
            speaker_profile = speaker_map.get(speaker_key, {})
            segment_speaker = int(segment.get("speaker", speaker_profile.get("speaker", speaker)))
            segment_settings = {
                **settings,
                **speaker_profile.get("settings", {}),
                **segment.get("voicevox", {}),
            }
            wav_path = segment_dir / f"{segment_id}.wav"
            query_url = f"{base_url}/audio_query?{urllib.parse.urlencode({'text': segment['text'], 'speaker': segment_speaker})}"
            query_bytes, _ = post_json(query_url)
            query = json.loads(query_bytes.decode("utf-8"))
            for key, value in segment_settings.items():
                if key in query:
                    query[key] = value
            if args.force or not wav_path.exists():
                synthesis_url = f"{base_url}/synthesis?{urllib.parse.urlencode({'speaker': segment_speaker})}"
                audio_bytes, content_type = post_json(synthesis_url, query)
                if content_type not in {"audio/wav", "audio/x-wav", "application/octet-stream"}:
                    raise RuntimeError(f"VOICEVOXの応答がWAVではありません: {content_type}")
                wav_path.write_bytes(audio_bytes)

            params, frames, header_duration = wav_spec(wav_path)
            probed_duration = media_duration(wav_path)
            if abs(header_duration - probed_duration) > 0.03:
                raise RuntimeError(f"WAV実尺が一致しません: {wav_path}")
            segment_records.append(
                {
                    "id": segment_id,
                    "scene_id": scene["id"],
                    "text": segment["text"],
                    "highlight": segment.get("highlight", []),
                    "speaker": segment_speaker,
                    "speaker_key": speaker_key,
                    "hold_after": float(segment.get("hold_after", default_gap)),
                    "wav": wav_path.relative_to(project_dir).as_posix(),
                    "ffprobe_duration": probed_duration,
                    "mouth_timing": audio_query_mouth_timing(query, probed_duration),
                    "params": params,
                    "frames": frames,
                }
            )

    narration_path = project_dir / "audio" / "narration.wav"
    narration_path.parent.mkdir(parents=True, exist_ok=True)
    first_params = segment_records[0]["params"]
    cursor_frames = 0
    timing_segments: list[dict[str, Any]] = []
    with wave.open(str(narration_path), "wb") as output:
        output.setparams(first_params)
        for record in segment_records:
            params = record["params"]
            if (params.nchannels, params.sampwidth, params.framerate, params.comptype) != (
                first_params.nchannels,
                first_params.sampwidth,
                first_params.framerate,
                first_params.comptype,
            ):
                raise RuntimeError("VOICEVOXのWAV形式がセグメント間で一致しません")
            start = cursor_frames / first_params.framerate
            output.writeframes(record["frames"])
            cursor_frames += params.nframes
            end = cursor_frames / first_params.framerate
            timing_segments.append(
                {
                    key: record[key]
                    for key in (
                        "id",
                        "scene_id",
                        "text",
                        "highlight",
                        "speaker",
                        "speaker_key",
                        "hold_after",
                        "wav",
                        "ffprobe_duration",
                        "mouth_timing",
                    )
                }
                | {"start": start, "end": end, "audio_duration": end - start}
            )
            silence_frames = round(record["hold_after"] * first_params.framerate)
            output.writeframes(b"\x00" * silence_frames * first_params.nchannels * first_params.sampwidth)
            cursor_frames += silence_frames

    scenes: list[dict[str, Any]] = []
    for scene in project["scenes"]:
        items = [item for item in timing_segments if item["scene_id"] == scene["id"]]
        start = items[0]["start"]
        last = items[-1]
        end = last["end"] + last["hold_after"]
        scenes.append({"id": scene["id"], "start": start, "end": end, "duration": end - start})

    combined_duration = media_duration(narration_path)
    timing = {
        "schema_version": 2,
        "voicevox_engine_version": engine_version,
        "speaker": speaker,
        "speakers": speaker_map,
        "sample_rate": first_params.framerate,
        "channels": first_params.nchannels,
        "total_duration": combined_duration,
        "segments": timing_segments,
        "scenes": scenes,
    }
    write_json(project_dir / "audio" / "timing.json", timing)
    print(json.dumps({"narration": str(narration_path), "duration": combined_duration, "segments": len(timing_segments)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
