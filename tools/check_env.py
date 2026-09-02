from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

from common import find_executable


def voicevox_version() -> str | None:
    base = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/version", timeout=2) as response:
            return response.read().decode("utf-8").strip('"')
    except Exception:
        return None


def main() -> int:
    try:
        import opentimelineio

        otio_version = getattr(opentimelineio, "__version__", "installed")
    except Exception:
        otio_version = None

    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    configured_client_file = os.environ.get("YOUTUBE_CLIENT_SECRETS_FILE", "").strip()
    client_file = (
        Path(configured_client_file).expanduser()
        if configured_client_file
        else local / "VideoAutomationEngine" / "youtube-client-secret.json"
    )
    youtube_env_credentials = bool(os.environ.get("YOUTUBE_CLIENT_ID")) and bool(
        os.environ.get("YOUTUBE_CLIENT_SECRET")
    )
    checks = {
        "python": sys.version.split()[0],
        "ffmpeg": str(find_executable("ffmpeg") or ""),
        "ffprobe": str(find_executable("ffprobe") or ""),
        "kdenlive": str(find_executable("kdenlive") or ""),
        "melt": str(find_executable("melt") or ""),
        "voicevox_engine": str(find_executable("voicevox_engine") or ""),
        "voicevox_api_version": voicevox_version(),
        "opentimelineio": otio_version,
        "brave_search_key_present": bool(os.environ.get("BRAVE_SEARCH_API_KEY")),
        "youtube_oauth_client_present": youtube_env_credentials or client_file.is_file(),
        "youtube_oauth_client_source": "environment" if youtube_env_credentials else str(client_file),
    }
    required = ["ffmpeg", "ffprobe", "kdenlive", "melt", "voicevox_engine", "opentimelineio"]
    checks["ready"] = all(checks[item] for item in required) and checks["voicevox_api_version"] is not None
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    if not checks["ready"]:
        print("VOICEVOXが停止中なら tools/start_voicevox.ps1 を実行してください。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
