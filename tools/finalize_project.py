from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="動画を最終検証し、合格時だけYouTubeへ非公開アップロードします")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("youtube_args", nargs=argparse.REMAINDER, help="-- 以降をupload_youtube.pyへ渡します")
    args = parser.parse_args()

    tools_dir = Path(__file__).resolve().parent
    project_dir = args.project_dir.resolve()
    subprocess.run(
        [sys.executable, str(tools_dir / "validate_project.py"), str(project_dir)],
        check=True,
    )
    upload_args = args.youtube_args[1:] if args.youtube_args[:1] == ["--"] else args.youtube_args
    subprocess.run(
        [sys.executable, str(tools_dir / "upload_youtube.py"), str(project_dir), *upload_args],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
