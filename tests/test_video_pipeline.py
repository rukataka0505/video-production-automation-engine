from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import opentimelineio as otio


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import build_ass
import build_timeline
import render_video
import validate_project
from common import delivery_filename, scene_shots, shot_durations


class ShotModelTests(unittest.TestCase):
    def test_multiple_shots_share_unassigned_scene_time(self) -> None:
        scene = {
            "id": "scene-1",
            "shots": [
                {"path": "a.mp4", "duration_seconds": 2},
                {"path": "b.mp4"},
                {"path": "c.jpg"},
            ],
        }
        self.assertEqual(shot_durations(scene, 8), [2, 3, 3])
        self.assertEqual(render_video.shot_frame_counts([2, 3, 3], 8, 30), [60, 90, 90])

    def test_legacy_visual_remains_readable(self) -> None:
        visual = {"path": "legacy.jpg", "type": "image"}
        self.assertEqual(scene_shots({"id": "old", "visual": visual}), [visual])

    def test_final_mp4_is_a_valid_delivery_filename(self) -> None:
        self.assertEqual(delivery_filename({"delivery": {"filename": "final.mp4"}}), "final.mp4")


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

    def test_motioned_still_routes_to_mlt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory)
            (project_dir / "still.jpg").write_bytes(b"image")
            with patch.object(render_video, "make_mlt_still_clip") as mlt_mock, patch.object(
                render_video, "run"
            ) as run_mock:
                render_video.make_shot_clip(
                    Path("ffmpeg"),
                    Path("melt"),
                    project_dir,
                    "scene-1",
                    1,
                    {"path": "still.jpg", "type": "image", "motion": "zoom_in"},
                    60,
                    project_dir / "shot.mp4",
                    1920,
                    1080,
                    30,
                    project_dir / "profile",
                    {},
                )
            mlt_mock.assert_called_once()
            run_mock.assert_not_called()

    def test_mlt_still_command_uses_qtblend_transform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_dir = Path(directory)
            source = project_dir / "still.jpg"
            source.write_bytes(b"image")
            with patch.object(render_video, "image_size", return_value=(1920, 1080)), patch.object(
                render_video, "run"
            ) as run_mock:
                render_video.make_mlt_still_clip(
                    Path("melt"),
                    project_dir,
                    source,
                    project_dir / "shot.mp4",
                    project_dir / "profile",
                    60,
                    1920,
                    1080,
                    "pan_left",
                    {},
                )
            command = [str(value) for value in run_mock.call_args.args[0]]
            command_text = " ".join(command)
            self.assertIn("-filter", command)
            self.assertIn("qtblend", command)
            self.assertTrue(any(value.startswith("rect=") for value in command))
            self.assertNotIn("zoompan", command_text)

    def test_ffmpeg_visual_filter_has_no_motion_engine(self) -> None:
        self.assertEqual(
            render_video.visual_filter(1920, 1080, 30),
            "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,format=yuv420p",
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


def rate_time(seconds: float) -> otio.opentime.RationalTime:
    return otio.opentime.RationalTime(seconds * 30, 30)


def external_clip(name: str, path: Path, duration: float = 2.0) -> otio.schema.Clip:
    reference = otio.schema.ExternalReference(
        target_url=str(path.resolve()),
        available_range=otio.opentime.TimeRange(rate_time(0), rate_time(duration)),
    )
    return otio.schema.Clip(
        name=name,
        media_reference=reference,
        source_range=otio.opentime.TimeRange(rate_time(0), rate_time(duration)),
    )


def make_timeline(project_dir: Path) -> otio.schema.Timeline:
    timeline = otio.schema.Timeline(name="テスト")
    visual = otio.schema.Track(name="V1 Visuals", kind=otio.schema.TrackKind.Video)
    visual.append(external_clip("still", project_dir / "still.jpg"))
    narration = otio.schema.Track(name="A1 Narration", kind=otio.schema.TrackKind.Audio)
    narration.append(external_clip("line-1", project_dir / "audio" / "segments" / "line-1.wav"))
    timeline.tracks.extend([visual, narration])
    return timeline


class ValidatorTests(unittest.TestCase):
    def make_project(self, root: Path) -> tuple[dict[str, object], dict[str, object], otio.schema.Timeline]:
        project = {
            "title": "テスト動画",
            "thumbnail": {"concept": "テスト構図", "subject": "主役", "text": "要点"},
            "delivery": {"filename": "final.mp4"},
            "video": {
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "target_duration_seconds": {"min": 100, "max": 120},
            },
            "scenes": [
                {
                    "id": "scene-1",
                    "narration": [{"id": "line-1", "text": "本文"}],
                    "shots": [{"path": "still.jpg", "type": "image"}],
                }
            ],
        }
        timing = {
            "total_duration": 2.0,
            "segments": [
                {
                    "id": "line-1",
                    "scene_id": "scene-1",
                    "text": "本文",
                    "start": 0.0,
                    "end": 2.0,
                    "audio_duration": 2.0,
                    "hold_after": 0.0,
                    "wav": "audio/segments/line-1.wav",
                }
            ],
            "scenes": [{"id": "scene-1", "start": 0.0, "end": 2.0, "duration": 2.0}],
        }
        (root / "audio" / "segments").mkdir(parents=True)
        (root / "subtitles").mkdir()
        (root / "timeline").mkdir()
        (root / "output").mkdir()
        (root / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
        (root / "audio" / "timing.json").write_text(json.dumps(timing, ensure_ascii=False), encoding="utf-8")
        (root / "audio" / "segments" / "line-1.wav").write_bytes(b"wav")
        (root / "still.jpg").write_bytes(b"image")
        (root / "subtitles" / "subtitles.ass").write_text(
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,本文\n",
            encoding="utf-8-sig",
        )
        (root / "timeline" / "edit.otio").write_text("timeline", encoding="utf-8")
        (root / "output" / "final.mp4").write_bytes(b"video")
        (root / "output" / "thumbnail.jpg").write_bytes(b"\xff\xd8\xffimage")
        return project, timing, make_timeline(root)

    def write_project(self, root: Path, project: dict[str, object]) -> None:
        (root / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

    def write_timing(self, root: Path, timing: dict[str, object]) -> None:
        (root / "audio" / "timing.json").write_text(json.dumps(timing, ensure_ascii=False), encoding="utf-8")

    def run_validator(
        self,
        root: Path,
        timeline: otio.schema.Timeline,
        *,
        media: dict[str, object] | None = None,
        ffprobe_error: Exception | None = None,
        decode_error: Exception | None = None,
        duration_overrides: dict[str, float] | None = None,
        otio_error: Exception | None = None,
    ) -> dict[str, object]:
        media = media or {
            "format": {"duration": "2.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1"},
                {"codec_type": "audio", "sample_rate": "44100"},
            ],
        }
        duration_overrides = duration_overrides or {}

        def fake_duration(path: Path) -> float:
            return duration_overrides.get(Path(path).name, 2.0)

        ffprobe_value = ffprobe_error if ffprobe_error is not None else media
        otio_value = otio_error if otio_error is not None else timeline
        run_value = decode_error if decode_error is not None else None
        with patch.object(validate_project, "ffprobe", side_effect=ffprobe_value if isinstance(ffprobe_value, Exception) else None, return_value=None if isinstance(ffprobe_value, Exception) else ffprobe_value), patch.object(
            validate_project, "media_duration", side_effect=fake_duration
        ), patch.object(validate_project, "find_executable", return_value=Path("ffmpeg")), patch.object(
            validate_project, "run", side_effect=run_value
        ), patch.object(
            validate_project.otio.adapters,
            "read_from_file",
            side_effect=otio_value if isinstance(otio_value, Exception) else None,
            return_value=None if isinstance(otio_value, Exception) else otio_value,
        ):
            return validate_project.validate_project(root)

    def test_minimal_complete_project_passes_without_optional_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            for relative in [
                "brief.md",
                "script.md",
                "sources.json",
                "qa",
                "work/scenes",
                "work/scene-rendering.json",
            ]:
                self.assertFalse((root / relative).exists())
            result = self.run_validator(root, timeline)
            self.assertTrue(result["passed"], result["errors"])
            self.assertEqual(result["final_filename"], "final.mp4")
            self.assertEqual(result["warnings"], [])
            self.assertNotIn("duration_in_target_range", result)

    def test_optional_native_project_is_not_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            (root / "timeline" / "edit.kdenlive").write_text("not xml", encoding="utf-8")
            result = self.run_validator(root, timeline)
            self.assertTrue(result["passed"], result["errors"])

    def test_required_native_project_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _, timeline = self.make_project(root)
            project["deliverables"] = {"require_native_kdenlive": True}
            self.write_project(root, project)
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("Kdenlive" in error for error in result["errors"]))

    def test_missing_corrupt_and_structurally_broken_project_fail(self) -> None:
        with self.subTest("missing"), tempfile.TemporaryDirectory() as directory:
            result = validate_project.validate_project(Path(directory))
            self.assertFalse(result["passed"])
            self.assertTrue(any("project.jsonがありません" in error for error in result["errors"]))
        with self.subTest("corrupt"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "project.json").write_text("{", encoding="utf-8")
            result = validate_project.validate_project(root)
            self.assertFalse(result["passed"])
            self.assertTrue(any("読み取れません" in error for error in result["errors"]))
        with self.subTest("structure"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "project.json").write_text('{"title":"x","scenes":[]}', encoding="utf-8")
            result = validate_project.validate_project(root)
            self.assertFalse(result["passed"])
            self.assertTrue(any("scenes" in error for error in result["errors"]))

    def test_corrupt_final_video_and_decode_failure_fail(self) -> None:
        with self.subTest("probe"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            result = self.run_validator(root, timeline, ffprobe_error=RuntimeError("broken"))
            self.assertFalse(result["passed"])
            self.assertTrue(any("完成動画を読み取れません" in error for error in result["errors"]))
        with self.subTest("decode"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            result = self.run_validator(
                root,
                timeline,
                decode_error=subprocess.CalledProcessError(1, ["ffmpeg"]),
            )
            self.assertFalse(result["passed"])
            self.assertTrue(any("最後までデコード" in error for error in result["errors"]))

    def test_missing_required_files_fail(self) -> None:
        for relative, expected in [
            ("output/final.mp4", "完成動画がありません"),
            ("output/thumbnail.jpg", "サムネイルがありません"),
            ("subtitles/subtitles.ass", "ASS字幕がありません"),
            ("audio/timing.json", "audio/timing.jsonがありません"),
            ("timeline/edit.otio", "OTIOがありません"),
        ]:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, _, timeline = self.make_project(root)
                (root / relative).unlink()
                result = self.run_validator(root, timeline)
                self.assertFalse(result["passed"])
                self.assertTrue(any(expected in error for error in result["errors"]))

    def test_thumbnail_must_be_jpeg_and_sixteen_by_nine(self) -> None:
        with self.subTest("jpeg"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            (root / "output" / "thumbnail.jpg").write_bytes(b"not-jpeg")
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("有効なJPEG" in error for error in result["errors"]))
        with self.subTest("aspect"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            media = {
                "format": {"duration": "2.0"},
                "streams": [
                    {"codec_type": "video", "width": 1920, "height": 1000, "avg_frame_rate": "30/1"},
                    {"codec_type": "audio", "sample_rate": "44100"},
                ],
            }
            result = self.run_validator(root, timeline, media=media)
            self.assertFalse(result["passed"])
            self.assertTrue(any("16:9" in error for error in result["errors"]))

    def test_missing_final_stream_and_delivery_mismatch_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            media = {
                "format": {"duration": "2.0"},
                "streams": [{"codec_type": "video", "width": 1280, "height": 720, "avg_frame_rate": "24/1"}],
            }
            result = self.run_validator(root, timeline, media=media)
            self.assertFalse(result["passed"])
            self.assertTrue(any("音声ストリーム" in error for error in result["errors"]))
            self.assertTrue(any("納品仕様" in error for error in result["errors"]))

    def test_subtitle_text_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            (root / "subtitles" / "subtitles.ass").write_text(
                "[Events]\nDialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,別本文\n",
                encoding="utf-8-sig",
            )
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("字幕本文" in error for error in result["errors"]))

    def test_missing_required_shot_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            (root / "still.jpg").unlink()
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("必須shot素材" in error for error in result["errors"]))

    def test_video_shot_range_errors_fail(self) -> None:
        for source_start, expected in [(5.0, "source_start"), (4.0, "残り尺")]:
            with self.subTest(source_start=source_start), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project, _, timeline = self.make_project(root)
                (root / "clip.mp4").write_bytes(b"video")
                project["scenes"][0]["shots"] = [
                    {"path": "clip.mp4", "type": "video", "source_start": source_start}
                ]
                self.write_project(root, project)
                result = self.run_validator(root, timeline, duration_overrides={"clip.mp4": 5.0})
                self.assertFalse(result["passed"])
                self.assertTrue(any(expected in error for error in result["errors"]))

    def test_timing_identity_duration_and_wav_failures_fail(self) -> None:
        with self.subTest("identity"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, timing, timeline = self.make_project(root)
            timing["segments"][0]["id"] = "wrong"
            self.write_timing(root, timing)
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("segment ID" in error for error in result["errors"]))
        with self.subTest("duration"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, timing, timeline = self.make_project(root)
            timing["total_duration"] = 99.0
            self.write_timing(root, timing)
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("total_duration" in error for error in result["errors"]))
        with self.subTest("wav"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            (root / "audio" / "segments" / "line-1.wav").unlink()
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("WAV" in error for error in result["errors"]))

    def test_otio_broken_reference_range_and_read_failures_fail(self) -> None:
        with self.subTest("reference"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            timeline.tracks[0][0].media_reference.target_url = str(root / "missing.jpg")
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("OTIOが参照" in error for error in result["errors"]))
        with self.subTest("range"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            timeline.tracks[0][0].source_range = otio.opentime.TimeRange(rate_time(1), rate_time(2))
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("素材尺外" in error for error in result["errors"]))
        with self.subTest("read"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            result = self.run_validator(root, timeline, otio_error=RuntimeError("broken"))
            self.assertFalse(result["passed"])
            self.assertTrue(any("OTIOを読み取れません" in error for error in result["errors"]))
        with self.subTest("duration"), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, timeline = self.make_project(root)
            for track in timeline.tracks:
                track[0].source_range = otio.opentime.TimeRange(rate_time(0), rate_time(1))
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("重大に不一致" in error for error in result["errors"]))

    def test_bgm_project_requires_bgm_track(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _, timeline = self.make_project(root)
            (root / "bgm.wav").write_bytes(b"bgm")
            project["bgm"] = {"path": "bgm.wav"}
            self.write_project(root, project)
            result = self.run_validator(root, timeline)
            self.assertFalse(result["passed"])
            self.assertTrue(any("A2 BGM" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
