from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _first_file(patterns: Iterable[Path]) -> Path | None:
    for pattern in patterns:
        parent = pattern.parent
        if not parent.exists():
            continue
        matches = sorted(parent.glob(pattern.name), reverse=True)
        if matches:
            return matches[0]
    return None


def find_executable(name: str) -> Path | None:
    env_map = {
        "ffmpeg": "VIDEO_FFMPEG",
        "ffprobe": "VIDEO_FFPROBE",
        "kdenlive": "KDENLIVE_PATH",
        "melt": "MLT_MELT",
        "voicevox_engine": "VOICEVOX_ENGINE",
    }
    env_name = env_map.get(name)
    if env_name and os.environ.get(env_name):
        candidate = Path(os.environ[env_name]).expanduser()
        if candidate.is_file():
            return candidate.resolve()

    command_name = "run" if name == "voicevox_engine" else name
    located = shutil.which(command_name)
    if located:
        return Path(located).resolve()

    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    winget = local / "Microsoft" / "WinGet" / "Packages"
    patterns: dict[str, list[Path]] = {
        "ffmpeg": [winget / "Gyan.FFmpeg_*" / "ffmpeg-*" / "bin" / "ffmpeg.exe"],
        "ffprobe": [winget / "Gyan.FFmpeg_*" / "ffmpeg-*" / "bin" / "ffprobe.exe"],
        "kdenlive": [local / "Programs" / "Kdenlive" / "bin" / "kdenlive.exe"],
        "melt": [local / "Programs" / "Kdenlive" / "bin" / "melt.exe"],
        "voicevox_engine": [
            winget / "HiroshibaKazuyuki.VOICEVOX_*" / "VOICEVOX" / "vv-engine" / "run.exe"
        ],
    }
    expanded: list[Path] = []
    for pattern in patterns.get(name, []):
        parts = pattern.parts
        current = Path(parts[0])
        for part in parts[1:]:
            if "*" in part:
                matches = sorted(current.glob(part), reverse=True) if current.exists() else []
                if not matches:
                    current = current / part
                    break
                current = matches[0]
            else:
                current = current / part
        expanded.append(current)
    return next((path.resolve() for path in expanded if path.is_file()), None)


def run(command: list[str | Path], *, cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    printable = " ".join(f'"{item}"' if " " in str(item) else str(item) for item in command)
    print(f"$ {printable}")
    return subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def ffprobe(path: Path) -> dict[str, Any]:
    executable = find_executable("ffprobe")
    if not executable:
        raise RuntimeError("ffprobeが見つかりません。READMEのセットアップを確認してください。")
    result = run(
        [executable, "-v", "error", "-show_format", "-show_streams", "-of", "json", path.resolve()],
        capture=True,
    )
    return json.loads(result.stdout)


def media_duration(path: Path) -> float:
    info = ffprobe(path)
    duration = info.get("format", {}).get("duration")
    if duration is None:
        for stream in info.get("streams", []):
            if stream.get("duration") is not None:
                duration = stream["duration"]
                break
    if duration is None:
        raise RuntimeError(f"メディア尺を取得できません: {path}")
    return float(duration)


def project_file(project_dir: Path, relative: str) -> Path:
    path = (project_dir / relative).resolve()
    root = project_dir.resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"プロジェクト外の相対パスです: {relative}")
    return path


def scene_shots(scene: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the current shot list while keeping older projects readable."""
    if "shots" in scene:
        shots = scene["shots"]
        if not isinstance(shots, list) or not shots:
            raise ValueError(f"シーンのshotsが空です: {scene.get('id', '(no id)')}")
        return shots
    if isinstance(scene.get("visual"), dict):
        return [scene["visual"]]
    raise ValueError(f"シーンにshotsがありません: {scene.get('id', '(no id)')}")


def shot_durations(scene: dict[str, Any], scene_duration: float) -> list[float]:
    """Fit shot cuts to measured narration time without changing narration length."""
    shots = scene_shots(scene)
    if scene_duration <= 0:
        raise ValueError(f"シーンの実測尺が0秒以下です: {scene.get('id', '(no id)')}")

    durations: list[float | None] = []
    specified_total = 0.0
    unspecified: list[int] = []
    for index, shot in enumerate(shots):
        value = shot.get("duration_seconds")
        if value is None:
            durations.append(None)
            unspecified.append(index)
            continue
        duration = float(value)
        if duration <= 0:
            raise ValueError(f"shotのduration_secondsは正数にしてください: {scene.get('id')}[{index}]")
        durations.append(duration)
        specified_total += duration

    remaining = scene_duration - specified_total
    if unspecified:
        if remaining <= 0:
            raise ValueError(f"shot尺の合計がシーン実測尺以上です: {scene.get('id')}")
        share = remaining / len(unspecified)
        for index in unspecified:
            durations[index] = share
    else:
        if abs(remaining) > 0.1:
            raise ValueError(
                f"shot尺の合計がシーン実測尺と一致しません: {scene.get('id')} "
                f"shots={specified_total:.3f}s scene={scene_duration:.3f}s"
            )
        durations[-1] = float(durations[-1]) + remaining

    return [float(value) for value in durations]


def source_groups(value: Any) -> dict[str, list[dict[str, Any]]]:
    """Normalize the current grouped source registry and the legacy flat list."""
    groups = {"research_sources": [], "visual_assets": [], "audio_assets": []}
    if isinstance(value, dict):
        for key in groups:
            entries = value.get(key, [])
            if not isinstance(entries, list):
                raise ValueError(f"sources.jsonの{key}は配列にしてください")
            groups[key] = entries
        return groups
    if not isinstance(value, list):
        raise ValueError("sources.jsonは分類済みオブジェクトまたは旧形式の配列である必要があります")

    for entry in value:
        source_type = str(entry.get("type", "")).lower()
        if source_type in {"image", "video", "graphic", "generated_graphic", "animation", "document_excerpt"}:
            groups["visual_assets"].append(entry)
        elif source_type in {"audio", "music", "bgm"}:
            groups["audio_assets"].append(entry)
        else:
            groups["research_sources"].append(entry)
    return groups


def source_entries(value: Any) -> list[dict[str, Any]]:
    groups = source_groups(value)
    return groups["research_sources"] + groups["visual_assets"] + groups["audio_assets"]


def delivery_filename(project: dict[str, Any]) -> str:
    configured = str(project.get("delivery", {}).get("filename", "")).strip()
    if configured:
        candidate = configured
    else:
        title = str(project.get("title") or project.get("slug") or "完成動画").strip()
        candidate = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).rstrip(" .") + ".mp4"
    if Path(candidate).name != candidate or candidate in {".", ".."}:
        raise ValueError(f"完成動画のファイル名が不正です: {candidate}")
    if not candidate.lower().endswith(".mp4"):
        raise ValueError(f"完成動画のファイル名は.mp4で終える必要があります: {candidate}")
    if candidate.lower() == "final.mp4":
        raise ValueError("完成動画にはfinal.mp4ではなく内容を表すタイトルを付けてください")
    return candidate


def final_output_path(project_dir: Path, project: dict[str, Any]) -> Path:
    return project_dir.resolve() / "output" / delivery_filename(project)
