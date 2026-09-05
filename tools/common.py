from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def find_executable(name: str) -> Path | None:
    env_map = {
        "ffmpeg": "VIDEO_FFMPEG",
        "ffprobe": "VIDEO_FFPROBE",
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
    return candidate


def final_output_path(project_dir: Path, project: dict[str, Any]) -> Path:
    return project_dir.resolve() / "output" / delivery_filename(project)
