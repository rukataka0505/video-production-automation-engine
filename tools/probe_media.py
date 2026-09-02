from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import ffprobe, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="ffprobeのメディア情報をJSONで保存します")
    parser.add_argument("media", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    info = ffprobe(args.media)
    if args.output:
        write_json(args.output, info)
    else:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

