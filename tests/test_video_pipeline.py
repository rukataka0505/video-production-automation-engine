from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import build_ass
import build_timeline
import render_video
import validate_project
from common import scene_shots, shot_durations, source_groups


class ShotModelTests(unittest.TestCase):
    def test_multiple_shots_share_unassigned_scene_time(self) -> None:
        scene = {
            "id": "scene-1",
            "shots": [
                {"visual_intent": "導入", "path": "a.mp4", "duration_seconds": 2},
                {"visual_intent": "詳細", "path": "b.mp4"},
                {"visual_intent": "結論", "path": "c.jpg"},
            ],
        }
        self.assertEqual(shot_durations(scene, 8), [2, 3, 3])
        self.assertEqual(render_video.shot_frame_counts([2, 3, 3], 8, 30), [60, 90, 90])

    def test_legacy_visual_remains_readable(self) -> None:
        visual = {"path": "legacy.jpg", "type": "image"}
        self.assertEqual(scene_shots({"id": "old", "visual": visual}), [visual])

    def test_sources_are_separated_by_role(self) -> None:
        groups = source_groups(
            [
                {"id": "r", "type": "fact"},
                {"id": "v", "type": "video"},
                {"id": "a", "type": "audio"},
            ]
        )
        self.assertEqual([entry["id"] for entry in groups["research_sources"]], ["r"])
        self.assertEqual([entry["id"] for entry in groups["visual_assets"]], ["v"])
        self.assertEqual([entry["id"] for entry in groups["audio_assets"]], ["a"])


class SubtitleWrappingTests(unittest.TestCase):
    def test_katakana_and_latin_words_are_not_split(self) -> None:
        text = "サイバーキャブとOpenTimelineIOで編集する"
        wrapped = build_ass.wrap_japanese(text, 10, 2)
        self.assertEqual(wrapped.replace(r"\N", ""), text)
        self.assertNotIn(r"サイバー\Nキャブ", wrapped)
        self.assertNotIn(r"Open\NTimelineIO", wrapped)


class RenderCommandTests(unittest.TestCase):
    def test_video_shot_is_trimmed_without_stream_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory)
            source = project_dir / "clip.mp4"
            source.write_bytes(b"video")
            with patch.object(render_video, "media_duration", return_value=3.0), patch.object(
                render_video, "run"
            ) as run_mock:
                render_video.make_shot_clip(
                    Path("ffmpeg"),
                    None,
                    project_dir,
                    "scene-1",
                    1,
                    {"path": "clip.mp4", "type": "video", "source_start": 0.5},
                    60,
                    project_dir / "shot.mp4",
                    1920,
                    1080,
                    30,
                    project_dir / "profile",
                    {},
                )
            command = [str(value) for value in run_mock.call_args.args[0]]
            self.assertNotIn("-stream_loop", command)
            self.assertIn("-frames:v", command)

    def test_short_video_requires_another_shot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory)
            (project_dir / "clip.mp4").write_bytes(b"video")
            with patch.object(render_video, "media_duration", return_value=1.0):
                with self.assertRaisesRegex(ValueError, "別shot"):
                    render_video.make_shot_clip(
                        Path("ffmpeg"),
                        None,
                        project_dir,
                        "scene-1",
                        1,
                        {"path": "clip.mp4", "type": "video"},
                        60,
                        project_dir / "shot.mp4",
                        1920,
                        1080,
                        30,
                        project_dir / "profile",
                        {},
                    )

    def test_otio_video_clip_does_not_repeat_short_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.mp4"
            path.write_bytes(b"video")
            with patch.object(build_timeline, "media_duration", return_value=1.0):
                with self.assertRaisesRegex(ValueError, "別shot"):
                    build_timeline.visual_clips(
                        "shot",
                        path,
                        0,
                        2,
                        30,
                        {},
                        Path(directory),
                    )


class _Duration:
    def __init__(self, seconds: float):
        self.seconds = seconds

    def to_seconds(self) -> float:
        return self.seconds


class _Track:
    def __init__(self, name: str):
        self.name = name

    def find_clips(self) -> list[object]:
        return []


class _Marker:
    metadata = {"scene_id": "scene-1"}


class _Tracks(list):
    markers = [_Marker()]


class _Timeline:
    def __init__(self, subtitle_path: str):
        self.tracks = _Tracks([_Track("V1 Visuals"), _Track("A1 Narration")])
        self.metadata = {"project": {"subtitles": subtitle_path}}

    def duration(self) -> _Duration:
        return _Duration(7.0)


class ValidatorDurationTests(unittest.TestCase):
    def test_target_duration_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory)
            for relative in ["output", "subtitles", "timeline", "audio", "qa", "work/scenes"]:
                (project_dir / relative).mkdir(parents=True, exist_ok=True)
            project = {
                "title": "テスト動画",
                "delivery": {"filename": "テスト動画.mp4"},
                "video": {"width": 1920, "height": 1080, "fps": 30, "target_duration_seconds": {"min": 1, "max": 2}},
                "scenes": [
                    {
                        "id": "scene-1",
                        "narration": [{"id": "line-1", "text": "本文"}],
                        "shots": [{"visual_intent": "本文を示す", "path": "still.jpg", "type": "image"}],
                    }
                ],
            }
            timing = {
                "total_duration": 7.0,
                "segments": [{"id": "line-1", "scene_id": "scene-1", "text": "本文", "subtitle": "本文"}],
                "scenes": [{"id": "scene-1", "duration": 7.0}],
            }
            (project_dir / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
            (project_dir / "audio/timing.json").write_text(json.dumps(timing, ensure_ascii=False), encoding="utf-8")
            (project_dir / "sources.json").write_text(
                json.dumps({"research_sources": [], "visual_assets": [], "audio_assets": []}), encoding="utf-8"
            )
            (project_dir / "research.md").write_text("research", encoding="utf-8")
            (project_dir / "brief.md").write_text("brief", encoding="utf-8")
            (project_dir / "output/テスト動画.mp4").write_bytes(b"video")
            (project_dir / "subtitles/subtitles.ass").write_text(
                "Dialogue: 0,0:00:00.00,0:00:07.00,Default,,0,0,0,,本文\n", encoding="utf-8-sig"
            )
            (project_dir / "timeline/edit.otio").write_text("timeline", encoding="utf-8")
            (project_dir / "work/scenes/scene-1.mp4").write_bytes(b"scene")
            (project_dir / "work/scene-rendering.json").write_text(
                json.dumps({"renderer_version": 3, "scenes": [{"scene_id": "scene-1", "shots": []}]}), encoding="utf-8"
            )
            for index in range(4):
                (project_dir / "qa" / f"frame-{index}.png").write_bytes(b"frame")

            media = {
                "format": {"duration": "7.0"},
                "streams": [
                    {"codec_type": "video", "width": 1920, "height": 1080},
                    {"codec_type": "audio", "sample_rate": "48000"},
                ],
            }
            timeline = _Timeline("../subtitles/subtitles.ass")
            with patch.object(sys, "argv", ["validate_project.py", str(project_dir)]), patch.object(
                validate_project, "ffprobe", return_value=media
            ), patch.object(validate_project, "find_executable", return_value=Path("ffmpeg")), patch.object(
                validate_project, "run"
            ), patch.object(validate_project, "media_duration", return_value=7.0), patch.object(
                validate_project.otio.adapters, "read_from_file", return_value=timeline
            ):
                self.assertEqual(validate_project.main(), 0)

            result = json.loads((project_dir / "qa/validation.json").read_text(encoding="utf-8"))
            self.assertFalse(result["duration_in_target_range"])
            self.assertTrue(result["passed"])
            self.assertTrue(any("目安範囲外" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
