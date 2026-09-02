from __future__ import annotations

import argparse
from pathlib import Path

from common import find_executable, media_duration, read_json, run


def main() -> int:
    parser = argparse.ArgumentParser(description="動画から代表フレームとコンタクトシートを抽出します")
    parser.add_argument("video", type=Path)
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--project-dir", type=Path, help="全シーンの中間時点を抽出します")
    args = parser.parse_args()
    video = args.video.resolve()
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpegが見つかりません")
    output_dir = args.output_dir.resolve() if args.output_dir else video.parents[1] / "qa"
    output_dir.mkdir(parents=True, exist_ok=True)
    duration = media_duration(video)
    if args.project_dir:
        project_dir = args.project_dir.resolve()
        timing = read_json(project_dir / "audio" / "timing.json")
        samples = [
            (f"scene-{index:02d}-{scene['id']}", float(scene["start"]) + float(scene["duration"]) / 2)
            for index, scene in enumerate(timing["scenes"], start=1)
        ]
    else:
        fractions = [(index + 0.5) / args.count for index in range(args.count)]
        samples = [(f"frame-{index:02d}", duration * fraction) for index, fraction in enumerate(fractions, start=1)]
    frames: list[Path] = []
    for label, timestamp in samples:
        output = output_dir / f"{label}-{timestamp:06.2f}s.png"
        run([ffmpeg, "-y", "-ss", f"{timestamp:.3f}", "-i", video, "-frames:v", "1", output])
        frames.append(output)

    command: list[str | Path] = [ffmpeg, "-y"]
    for frame in frames:
        command += ["-i", frame]
    filters: list[str] = []
    for index in range(len(frames)):
        filters.append(f"[{index}:v]scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2[v{index}]")
    rows: list[str] = []
    for row_index in range(0, len(frames), 3):
        labels = "".join(f"[v{index}]" for index in range(row_index, min(row_index + 3, len(frames))))
        count = min(3, len(frames) - row_index)
        row_label = f"r{row_index // 3}"
        if count == 1:
            filters.append(f"{labels}pad=1920:360:0:0:black[{row_label}]")
        else:
            filters.append(f"{labels}hstack=inputs={count},pad=1920:360:0:0:black[{row_label}]")
        rows.append(f"[{row_label}]")
    if len(rows) > 1:
        filters.append(f"{''.join(rows)}vstack=inputs={len(rows)}[out]")
        output_label = "[out]"
    else:
        output_label = rows[0]
    contact_sheet = output_dir / ("scene-contact-sheet.jpg" if args.project_dir else "contact-sheet.jpg")
    command += ["-filter_complex", ";".join(filters), "-map", output_label, "-frames:v", "1", "-q:v", "2", contact_sheet]
    run(command)
    print(f"QA frames: {output_dir}\nContact sheet: {contact_sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
