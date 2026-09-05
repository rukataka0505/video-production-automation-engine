from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Any

from common import read_json, write_json

MOUTH_STATES = {"a", "i", "u", "e", "o", "n", "closed"}

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


CHARACTER_UUIDS = {
    "388f246b-8c41-4ac1-8e2d-5d79f3ff56d9": "zundamon",
    "7ffcb7ce-00ec-4bdc-82cd-45a8889e43ff": "metan",
}


class Voicevox:
    def __init__(self) -> None:
        self.url = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")
        self.version = self.get("version")
        self.voices = self.get("speakers")

    def get(self, endpoint: str) -> Any:
        with urllib.request.urlopen(f"{self.url}/{endpoint}", timeout=5) as response:
            return json.load(response)

    def post(self, endpoint: str, params: dict, payload: dict | None = None) -> bytes:
        request = urllib.request.Request(
            f"{self.url}/{endpoint}?{urllib.parse.urlencode(params)}",
            data=json.dumps(payload).encode() if payload is not None else b"",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()

    def identity(self, style_id: int) -> dict:
        for voice in self.voices:
            for style in voice["styles"]:
                if style["id"] == style_id and style.get("type", "talk") == "talk":
                    return {"uuid": voice["speaker_uuid"], "name": voice["name"],
                            "character": CHARACTER_UUIDS.get(voice["speaker_uuid"])}
        raise ValueError(f"VOICEVOXに読み上げ用の声がありません: {style_id}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        data = wav.readframes(frames)
        if frames <= 0 or len(data) != frames * wav.getnchannels() * wav.getsampwidth():
            raise ValueError("破損したWAVです")
        return frames / wav.getframerate()


def synthesize(client: Voicevox, cache: Path, text: str, style_id: int, settings: dict) -> tuple[dict, bool]:
    identity = client.identity(style_id)
    key_data = {"text": text, "style": style_id, "voice": identity["uuid"],
                "settings": settings, "engine": client.version}
    key = hashlib.sha256(json.dumps(key_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    wav = cache / f"{key}.wav"
    record_path = cache / f"{key}.json"
    try:
        record = read_json(record_path)
        if (record["key"] == key_data and record["sha256"] == hashlib.sha256(wav.read_bytes()).hexdigest()
                and abs(wav_duration(wav) - record["duration"]) < 1e-6
                and isinstance(record["query"], dict)
                and record["mouth"] == audio_query_mouth_timing(record["query"], record["duration"])):
            return {**record, **identity, "path": str(wav)}, True
    except (OSError, ValueError, KeyError, wave.Error, EOFError):
        pass
    query = json.loads(client.post("audio_query", {"text": text, "speaker": style_id}))
    for name, value in settings.items():
        if name not in query:
            raise ValueError(f"未対応のVOICEVOX設定: {name}")
        query[name] = value
    cache.mkdir(parents=True, exist_ok=True)
    temporary = wav.with_suffix(".tmp.wav")
    temporary.write_bytes(client.post("synthesis", {"speaker": style_id}, query))
    duration = wav_duration(temporary)
    temporary.replace(wav)
    record = {"key": key_data, "duration": duration, "query": query,
              "mouth": audio_query_mouth_timing(query, duration),
              "sha256": hashlib.sha256(wav.read_bytes()).hexdigest()}
    write_json(record_path, record)
    return {**record, **identity, "path": str(wav)}, False
