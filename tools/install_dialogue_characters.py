from __future__ import annotations

import argparse
import hashlib
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from common import REPO_ROOT, find_executable, run


SOURCE_URL = (
    "https://nightwork.sakura.ne.jp/ukagaka/shell/Shikokumetan_Zundamon_Shellkit/"
    "Shikokumetan_Zundamon_Shell%2820230806%29.zip"
)
SOURCE_SHA256 = "e54467c53bb95398b29e427dbc2cfd740fd494186c803a338f19ec0c0ccee658"
ARCHIVE_ROOT = "Shikokumetan_Zundamon_Shell(20230806)/"
OUTPUT_DIR = REPO_ROOT / "assets" / "dialogue-characters"


CHARACTERS: dict[str, dict[str, Any]] = {
    "zundamon": {
        "base": [
            "Zundamon/尻尾的なアレ.png",
            "Zundamon/服装1/いつもの服.png",
            "Zundamon/服装1/左腕/基本.png",
            "Zundamon/服装1/右腕/基本.png",
            "Zundamon/顔色/ほっぺ.png",
            "Zundamon/眉/普通眉.png",
            "Zundamon/目/目セット/普通白目.png",
            "Zundamon/目/目セット/黒目/普通目.png",
        ],
        "mouth": {
            "closed": "Zundamon/口/むふ.png",
            "open": "Zundamon/口/ほあ.png",
        },
        "foreground": ["Zundamon/枝豆/枝豆通常.png"],
    },
    "metan": {
        "base": [
            "Metan/ツインドリル右.png",
            "Metan/ツインドリル左.png",
            "Metan/白ロリ服/体.png",
            "Metan/白ロリ服/右腕/普通.png",
            "Metan/白ロリ服/左腕/普通.png",
            "Metan/顔色/普通.png",
            "Metan/眉/太眉ごきげん.png",
            "Metan/頭部アクセサリ/髪留めフリル.png",
            "Metan/頭部アクセサリ/髪留めハート.png",
            "Metan/頭部アクセサリ/ヘッドドレス.png",
            "Metan/目/目セット/普通白目.png",
            "Metan/目/目セット/黒目/普通目.png",
        ],
        "mouth": {
            "closed": "Metan/口/ほほえみ.png",
            "open": "Metan/口/わあー.png",
        },
        "foreground": ["Metan/前髪もみあげ.png"],
    },
}


def download_bundle(destination: Path) -> None:
    with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
        destination.write_bytes(response.read())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise RuntimeError(f"立ち絵アーカイブのSHA-256が一致しません: {digest}")


def compose_png(ffmpeg: Path, inputs: list[Path], output: Path) -> None:
    command: list[str | Path] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for path in inputs:
        command += ["-i", path]

    filters = ["[0:v]format=rgba[layer0]"]
    current = "layer0"
    for index in range(1, len(inputs)):
        layer = f"layer{index}"
        combined = f"combined{index}"
        filters.append(f"[{index}:v]format=rgba[{layer}]")
        filters.append(f"[{current}][{layer}]overlay=0:0:format=auto[{combined}]")
        current = combined
    filters.append(f"[{current}]format=rgba[out]")
    command += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-frames:v",
        "1",
        "-update",
        "1",
        "-c:v",
        "png",
        "-pix_fmt",
        "rgba",
        output,
    ]
    run(command)


def install(*, force: bool = False) -> list[Path]:
    outputs = [OUTPUT_DIR / f"{speaker}-{state}.png" for speaker in CHARACTERS for state in ("closed", "open")]
    if not force and all(path.is_file() for path in outputs):
        return outputs

    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("立ち絵の合成に必要なFFmpegが見つかりません")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dialogue-characters-") as directory:
        temp_dir = Path(directory)
        archive_path = temp_dir / "characters.zip"
        download_bundle(archive_path)
        with zipfile.ZipFile(archive_path, metadata_encoding="cp932") as archive:
            for speaker, spec in CHARACTERS.items():
                for state, mouth_path in spec["mouth"].items():
                    layer_names = [*spec["base"], mouth_path, *spec["foreground"]]
                    extracted: list[Path] = []
                    for index, name in enumerate(layer_names):
                        destination = temp_dir / f"{speaker}-{state}-{index:02d}.png"
                        destination.write_bytes(archive.read(ARCHIVE_ROOT + name))
                        extracted.append(destination)
                    compose_png(ffmpeg, extracted, OUTPUT_DIR / f"{speaker}-{state}.png")
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="掛け合い動画用の口パク立ち絵を既存素材から準備します")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    for path in install(force=args.force):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
