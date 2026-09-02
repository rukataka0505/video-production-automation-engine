from __future__ import annotations

import argparse
from pathlib import Path

from common import REPO_ROOT, read_json


def ass_color(value: str) -> str:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"不正な色です: {value}")
    red, green, blue = value[0:2], value[2:4], value[4:6]
    return f"&H00{blue}{green}{red}"


def ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{cs:02d}"


def wrap_japanese(text: str, width: int, max_lines: int) -> str:
    text = text.strip().replace("\n", "")
    if len(text) <= width:
        return text
    lines: list[str] = []
    remaining = text
    punctuation = "、。！？!?：: "
    while remaining and len(lines) < max_lines - 1:
        target = min(width, len(remaining))
        break_at = next((index for index in range(target, max(8, target - 7), -1) if remaining[index - 1] in punctuation), target)
        lines.append(remaining[:break_at].strip())
        remaining = remaining[break_at:].strip()
    if remaining:
        lines.append(remaining)
    return r"\N".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="実測タイミングからASS字幕を作ります")
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    project_dir = args.project_dir.resolve()
    timing = read_json(project_dir / "audio" / "timing.json")
    project = read_json(project_dir / "project.json")
    style = {**read_json(REPO_ROOT / "style.json")["subtitles"], **project.get("subtitles", {})}
    video = read_json(REPO_ROOT / "style.json")["video"] | project.get("video", {})

    primary = ass_color(style["primary_color"])
    emphasis = ass_color(style["emphasis_color"])
    outline = ass_color(style["outline_color"])
    dialogue = style.get("dialogue", {})
    speaker_styles = dialogue.get("speaker_styles", {})

    def ass_style(name: str, primary_color: str, emphasis_color: str, panel_color: str) -> str:
        return (
            f"Style: {name},{style['font']},{style['size']},{ass_color(primary_color)},"
            f"{ass_color(emphasis_color)},{ass_color(panel_color)},&H70000000,-1,0,0,0,100,100,0,0,"
            f"{style.get('border_style', 1)},{style['outline']},{style['shadow']},2,72,72,{style['margin_vertical']},1"
        )

    style_lines = [
        ass_style("Default", style["primary_color"], style["emphasis_color"], style["outline_color"])
    ]
    style_name_by_speaker: dict[str, str] = {}
    for speaker_key, speaker_style in speaker_styles.items():
        style_name = speaker_key.capitalize()
        style_name_by_speaker[speaker_key] = style_name
        style_lines.append(
            ass_style(
                style_name,
                speaker_style.get("text_color", style["primary_color"]),
                speaker_style.get("emphasis_color", style["emphasis_color"]),
                speaker_style.get("panel_color", style["outline_color"]),
            )
        )
    header = f"""[Script Info]
Title: {project['title']}
ScriptType: v4.00+
PlayResX: {video['width']}
PlayResY: {video['height']}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{chr(10).join(style_lines)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for segment in timing["segments"]:
        speaker_key = segment.get("speaker_key", "default")
        speaker_style = speaker_styles.get(speaker_key, {})
        segment_primary = ass_color(speaker_style.get("text_color", style["primary_color"]))
        segment_emphasis = ass_color(speaker_style.get("emphasis_color", style["emphasis_color"]))
        style_name = style_name_by_speaker.get(speaker_key, "Default")
        text = segment.get("subtitle", segment["text"])
        text = wrap_japanese(text, int(style["max_chars_per_line"]), int(style["max_lines"]))
        text = text.replace("{", "｛").replace("}", "｝")
        for word in segment.get("highlight", []):
            text = text.replace(word, f"{{\\c{segment_emphasis}}}{word}{{\\c{segment_primary}}}")
        events.append(
            f"Dialogue: 0,{ass_time(segment['start'])},{ass_time(segment['end'])},{style_name},{speaker_key},0,0,0,,{text}"
        )
    output = project_dir / "subtitles" / "subtitles.ass"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    print(f"ASS字幕: {output} ({len(events)} cues)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
