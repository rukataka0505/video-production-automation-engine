from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from common import REPO_ROOT, ffprobe, final_output_path, find_executable, project_file, read_json, run, write_json
from speech import Voicevox, synthesize


def number(value, name: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name}: {minimum}以上の有限数が必要です")
    return float(value)


def load_project(root: Path) -> dict:
    project = read_json(root / "project.json")
    if not isinstance(project.get("title"), str) or not project["title"].strip():
        raise ValueError("titleが必要です")
    if "scenes" in project or not isinstance(project.get("beats"), list) or not project["beats"]:
        raise ValueError("新形式のbeatsが必要です。旧形式の移行機能はありません")
    voices = project.get("voices", {"narrator": {"style_id": 3}})
    if not isinstance(voices, dict) or not voices:
        raise ValueError("voicesが空です")
    for name, voice in voices.items():
        if not isinstance(voice.get("style_id"), int) or isinstance(voice["style_id"], bool):
            raise ValueError(f"voices.{name}.style_idはVOICEVOXの整数IDです")
    ids: set[str] = set()
    for beat in project["beats"]:
        for item in [beat, *beat.get("lines", [])]:
            key = item.get("id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or key in ids:
                raise ValueError(f"IDは全体で一意の英数字・ハイフン・下線にしてください: {key}")
            ids.add(key)
        if not beat.get("lines") and "duration" not in beat:
            raise ValueError(f"{beat['id']}: 無言のbeatにはdurationが必要です")
        if "duration" in beat:
            number(beat["duration"], beat["id"] + ".duration", 0.001)
        for line in beat.get("lines", []):
            if not isinstance(line.get("text"), str) or not line["text"].strip():
                raise ValueError(f"{line['id']}: textが必要です")
            if len(voices) > 1 and "voice" not in line:
                raise ValueError(f"{line['id']}: 複数音声ではvoiceを指定してください")
            if line.get("voice", next(iter(voices))) not in voices:
                raise ValueError(f"{line['id']}: 未定義のvoiceです")
            if "gap" in line:
                number(line["gap"], line["id"] + ".gap")
        if not isinstance(beat.get("visuals"), list) or not beat["visuals"]:
            raise ValueError(f"{beat['id']}: visualsが必要です")
    project["voices"] = voices
    final_output_path(root, project)
    return project


def frame(seconds: float, fps: int) -> int:
    return math.floor(seconds * fps + 0.5)


def resolve_time(value, lines: dict, duration: float) -> float:
    if value is None:
        return duration
    if isinstance(value, (int, float)):
        return number(value, "time")
    if not isinstance(value, dict) or value.get("line") not in lines or value.get("edge", "start") not in {"start", "end"}:
        raise ValueError(f"時刻の発話参照が不正です: {value}")
    offset = value.get("offset", 0)
    number(offset, "offset", -1e6)
    return lines[value["line"]][value.get("edge", "start")] + offset


def timed_event(event: dict, lines: dict, duration: float, start: float, fps: int) -> dict:
    first = resolve_time(event.get("from", 0), lines, duration)
    last = resolve_time(event.get("to"), lines, duration)
    if first < 0 or last > duration + 1e-6 or last <= first:
        raise ValueError(f"演出区間がbeatの範囲外です: {first:.3f}..{last:.3f} / {duration:.3f}")
    begin, end = frame(start + first, fps), frame(start + last, fps)
    if end <= begin:
        raise ValueError("演出区間が1フレーム未満です")
    return {**event, "from": begin, "to": end}


def asset(root: Path, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("素材pathは文字列です")
    path = project_file(root, value)
    if not path.is_file():
        raise ValueError(f"素材がありません: {value}")
    return path.relative_to(root).as_posix()


def prepare(root: Path, project: dict, client=None) -> dict:
    style = read_json(REPO_ROOT / "style.json")
    video = {**style["video"], **project.get("video", {})}
    for key in ("width", "height", "fps"):
        number(video[key], key, 1)
        if int(video[key]) != video[key]:
            raise ValueError(f"{key}は整数にしてください")
    if video["width"] % 2 or video["height"] % 2:
        raise ValueError("映像サイズは偶数にしてください")
    if not any(abs(video["width"] / video["height"] - ratio) < 0.01 for ratio in (16 / 9, 9 / 16)):
        raise ValueError("共通レイアウトは16:9または9:16です")
    if video["height"] > video["width"]:
        for section in ("subtitles", "characters"):
            style[section] = {**style[section], **style["portrait"][section]}
    fps = int(video["fps"])
    client = client or Voicevox()
    cursor = 0.0
    records, beats, audio = [], [], []
    reused = generated = 0
    for beat in project["beats"]:
        local = 0.0
        lines = {}
        for line in beat.get("lines", []):
            voice = project["voices"][line.get("voice", next(iter(project["voices"])))]
            settings = {**style["voice"]["settings"], **voice.get("settings", {}), **line.get("settings", {})}
            record, cached = synthesize(client, root / "work" / "audio", line["text"], voice["style_id"], settings)
            reused += int(cached)
            generated += int(not cached)
            seconds = record["duration"]
            lines[line["id"]] = {"start": local, "end": local + seconds}
            start, end = frame(cursor + local, fps), frame(cursor + local + seconds, fps)
            records.append({"id": line["id"], "beat": beat["id"], "text": line["text"],
                            "from": start, "to": end, "character": record["character"],
                            "mouth": record["mouth"], "path": Path(record["path"]).relative_to(root).as_posix(),
                            "duration": seconds, "voice_name": record["name"]})
            local += seconds + line.get("gap", style["audio"]["gap"])
        duration = beat.get("duration", local)
        if duration < local - 1e-6:
            raise ValueError(f"{beat['id']}: durationが音声と間の合計より短いです")
        first, end = frame(cursor, fps), frame(cursor + duration, fps)
        if end <= first:
            raise ValueError(f"{beat['id']}: beatが1フレーム未満です")
        visuals = []
        for event in beat["visuals"]:
            kind = event.get("kind")
            if kind not in {"media", "compare", "diagram", "focus", "text", "custom"}:
                raise ValueError(f"{beat['id']}: 未対応のvisual.kind: {kind}")
            item = timed_event(event, lines, duration, cursor, fps)
            if kind == "media":
                item["path"] = asset(root, event.get("path"))
                item["media"] = "image" if Path(item["path"]).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else "video"
                if item["media"] == "video":
                    source = number(item.get("source_start", 0), "source_start")
                    info = ffprobe(root / item["path"])
                    if not any(s["codec_type"] == "video" for s in info["streams"]):
                        raise ValueError(f"動画ストリームがありません: {item['path']}")
                    if source + (item["to"] - item["from"]) / fps > float(info["format"]["duration"]) + 1 / fps:
                        raise ValueError(f"{beat['id']}: 動画素材の尺が足りません: {item['path']}")
            if kind == "compare":
                if len(item.get("items", [])) != 2:
                    raise ValueError("compareにはitemsが2つ必要です")
                if any(not isinstance(x.get(k), str) for x in item["items"] for k in ("label", "value")):
                    raise ValueError("compareの各項目に文字列のlabelとvalueが必要です")
                item["items"] = [{**x, **({"path": asset(root, x["path"])} if "path" in x else {})} for x in item["items"]]
            if kind in {"text", "focus"} and not isinstance(item.get("text"), str):
                raise ValueError(f"{kind}.textが必要です")
            if kind == "diagram":
                if not item.get("nodes"):
                    raise ValueError("diagram.nodesが必要です")
                if any(not isinstance(node.get("text"), str) for node in item["nodes"]):
                    raise ValueError("diagramの各nodeにtextが必要です")
                item["nodes"] = [{**node, "from": frame(cursor + resolve_time(node.get("at", event.get("from", 0)), lines, duration), fps)} for node in item["nodes"]]
                if any(not item["from"] <= node["from"] < item["to"] for node in item["nodes"]):
                    raise ValueError("図の段階表示時刻が表示区間の範囲外です")
            if kind == "custom" and not (root / "visuals.tsx").is_file():
                raise ValueError("customには案件直下のvisuals.tsxが必要です")
            if "rect" in item:
                if not isinstance(item["rect"], list) or len(item["rect"]) != 4:
                    raise ValueError("rectは[左, 上, 幅, 高さ]です")
                for value in item["rect"]:
                    number(value, "rect")
            if "fit" in item and item["fit"] not in {"contain", "cover"}:
                raise ValueError("fitはcontainまたはcoverです")
            visuals.append(item)
        beats.append({"id": beat["id"], "title": beat.get("title", ""), "from": first, "to": end, "visuals": visuals})
        for sound in beat.get("audio", []):
            item = timed_event(sound, lines, duration, cursor, fps)
            for key in ("loop", "duck"):
                if key in item and not isinstance(item[key], bool):
                    raise ValueError(f"audio.{key}はtrueまたはfalseです")
            item["path"] = asset(root, item.get("path"))
            info = ffprobe(root / item["path"])
            if not any(s["codec_type"] == "audio" for s in info["streams"]):
                raise ValueError(f"音声ストリームがありません: {item['path']}")
            source = number(item.get("source_start", 0), "audio.source_start")
            available = float(info["format"]["duration"])
            if source >= available or (not item.get("loop", False) and source + (item["to"] - item["from"]) / fps > available + 1 / fps):
                raise ValueError(f"音素材の尺が足りません: {item['path']}")
            for k in ("volume", "fade_in", "fade_out"):
                if k in item:
                    number(item[k], "audio." + k)
            audio.append(item)
        cursor += duration
    characters = style["characters"]
    for key in {x["character"] for x in records} - {None}:
        for state in ("closed", "a", "i", "u", "e", "o", "n"):
            if not (REPO_ROOT / characters["voices"][key][state]).is_file():
                raise ValueError(f"立ち絵がありません: {key}/{state}。install_dialogue_characters.pyを実行してください")
    result = {"title": project["title"], "video": video, "durationInFrames": frame(cursor, fps),
              "lines": records, "beats": beats, "audio": audio, "characters": characters,
              "subtitles": style["subtitles"],
              "mix": style["audio"], "speech": {"generated": generated, "reused": reused}}
    write_json(root / "work" / "timing.json", result)
    return result


def validate_output(root: Path, project: dict, timing: dict, output: Path, quality: str) -> dict:
    info = ffprobe(output)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not video or not audio:
        raise ValueError("完成動画の映像または音声がありません")
    fps = timing["video"]["fps"]
    expected = timing["durationInFrames"] / fps
    if abs(float(info["format"]["duration"]) - expected) > max(0.1, 2 / fps):
        raise ValueError("完成動画の尺が時間表と一致しません")
    scale = 0.5 if quality == "preview" else 1
    if (video["width"], video["height"]) != (int(timing["video"]["width"] * scale), int(timing["video"]["height"] * scale)):
        raise ValueError("完成動画の解像度が一致しません")
    from fractions import Fraction
    if abs(float(Fraction(video["avg_frame_rate"])) - fps) > 0.001:
        raise ValueError("完成動画が指定の固定FPSではありません")
    actual = [(line["id"], line["text"]) for line in timing["lines"]]
    wanted = [(line["id"], line["text"]) for beat in project["beats"] for line in beat.get("lines", [])]
    if actual != wanted:
        raise ValueError("字幕・音声本文が台本と一致しません")
    run([find_executable("ffmpeg"), "-v", "error", "-xerror", "-i", output, "-f", "null", "-"], capture=True)
    result = {"passed": True, "quality": quality, "file": output.relative_to(root).as_posix(),
              "duration": float(info["format"]["duration"]), "full_decode": "passed",
              "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    write_json(root / "output" / f"{quality}-validation.json", result)
    return result


def validate_thumbnail(root: Path) -> None:
    path = root / "output" / "thumbnail.jpg"
    if not path.is_file() or path.read_bytes()[:3] != b"\xff\xd8\xff":
        raise ValueError("output/thumbnail.jpgが必要です")
    info = ffprobe(path)["streams"][0]
    project = read_json(root / "project.json")
    video = {**read_json(REPO_ROOT / "style.json")["video"], **project.get("video", {})}
    portrait = video["height"] > video["width"]
    ratio = 9 / 16 if portrait else 16 / 9
    if info["height" if portrait else "width"] < 640 or abs(info["width"] / info["height"] - ratio) > 0.01:
        raise ValueError("サムネイルは動画と同じ画面比率で、横動画は幅640px以上、縦動画は高さ640px以上にしてください")


def normalize_loudness(source: Path, output: Path, duration: float) -> None:
    """Only loudness correction: picture packets are copied, never composed here."""
    samples = round(number(duration, "duration", 0.001) * 48000)
    run([find_executable("ffmpeg"), "-v", "error", "-y", "-i", source,
         "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
         "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,apad,atrim=end_sample={samples},asetpts=N/SR/TB",
         "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", output], capture=True)
