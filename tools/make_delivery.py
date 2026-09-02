from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common import REPO_ROOT, ffprobe, final_output_path, find_executable, read_json, run, write_json


RIGHTS_WARNING = (
    "この動画は個人利用を前提として生成されています。Web上から取得した画像・動画・音声等が含まれる可能性があります。"
    "YouTube、SNS、Web等で公開・配布・商用利用する場合は、使用素材の著作権・ライセンス・利用条件を確認してください。"
)


def duration(info: dict[str, Any]) -> float:
    value = info.get("format", {}).get("duration")
    if value is not None:
        return float(value)
    for stream in info.get("streams", []):
        if stream.get("duration") is not None:
            return float(stream["duration"])
    raise RuntimeError("メディア尺を取得できません")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="完成動画から任意の720p版を作ります")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--input", help="プロジェクト内の入力ファイル。省略時はproject.jsonのタイトル付き完成原本")
    parser.add_argument("--output", help="プロジェクト内の出力ファイル。省略時はstyle.jsonを使用")
    args = parser.parse_args()

    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpegが見つかりません")

    project_dir = args.project_dir.resolve()
    style = read_json(REPO_ROOT / "style.json")
    project = read_json(project_dir / "project.json")
    delivery = style["delivery"]
    input_path = (project_dir / args.input).resolve() if args.input else final_output_path(project_dir, project)
    output_path = (project_dir / (args.output or f"output/{input_path.stem}-720p.mp4")).resolve()
    if project_dir not in input_path.parents or project_dir not in output_path.parents:
        raise ValueError("入出力はプロジェクト内を指定してください")
    if not input_path.is_file():
        raise FileNotFoundError(f"完成動画がありません: {input_path}")
    if input_path == output_path:
        raise ValueError("原本と納品版は別ファイルにしてください")

    width = int(delivery["width"])
    height = int(delivery["height"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=yuv420p"
    )
    run(
        [
            ffmpeg,
            "-y",
            "-i",
            input_path,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            str(delivery["video_preset"]),
            "-crf",
            str(delivery["video_crf"]),
            "-c:a",
            "aac",
            "-b:a",
            str(delivery["audio_bitrate"]),
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            output_path,
        ]
    )

    source_info = ffprobe(input_path)
    output_info = ffprobe(output_path)
    video_streams = [stream for stream in output_info.get("streams", []) if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in output_info.get("streams", []) if stream.get("codec_type") == "audio"]
    if len(video_streams) != 1 or len(audio_streams) < 1:
        raise RuntimeError("納品版の映像または音声ストリームが不正です")
    video = video_streams[0]
    if int(video.get("width", 0)) != width or int(video.get("height", 0)) != height:
        raise RuntimeError(f"納品版の解像度が不正です: {video.get('width')}x{video.get('height')}")
    source_duration = duration(source_info)
    output_duration = duration(output_info)
    if abs(source_duration - output_duration) > 0.25:
        raise RuntimeError(f"原本と納品版の尺が一致しません: {source_duration:.3f}s / {output_duration:.3f}s")

    run([ffmpeg, "-xerror", "-v", "error", "-i", output_path, "-f", "null", "-"], capture=True)
    manifest = {
        "status": "verified",
        "source": input_path.relative_to(project_dir).as_posix(),
        "file": output_path.relative_to(project_dir).as_posix(),
        "width": width,
        "height": height,
        "duration_seconds": round(output_duration, 6),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio_streams[0].get("codec_name"),
        "audio_sample_rate": int(audio_streams[0].get("sample_rate", 0)),
        "size_bytes": output_path.stat().st_size,
        "sha256": sha256(output_path),
        "decode_check": "passed",
        "rights_warning": RIGHTS_WARNING,
    }
    write_json(project_dir / "output" / "delivery.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
