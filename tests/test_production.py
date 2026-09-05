from __future__ import annotations
import copy
import io
import os
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import time
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from common import write_json
from production import load_project, prepare, resolve_time, timed_event, normalize_loudness
from speech import Voicevox, synthesize
from video import state, start, delivery_check


class FakeVoicevox(Voicevox):
    def __init__(self):
        self.version = "test-1"
        self.voices = [
            {"name": "ずんだもん", "speaker_uuid": "388f246b-8c41-4ac1-8e2d-5d79f3ff56d9", "styles": [{"id": 3}, {"id": 1}]},
            {"name": "四国めたん", "speaker_uuid": "7ffcb7ce-00ec-4bdc-82cd-45a8889e43ff", "styles": [{"id": 2}]},
            {"name": "別の声", "speaker_uuid": "other", "styles": [{"id": 8}]},
        ]
        self.calls = []

    def post(self, endpoint, params, payload=None):
        self.calls.append(endpoint)
        if endpoint == "audio_query":
            return json.dumps({"speedScale": 1, "pitchScale": 0, "intonationScale": 1, "volumeScale": 1,
                "prePhonemeLength": .05, "postPhonemeLength": .05, "outputSamplingRate": 48000, "outputStereo": False,
                "accent_phrases": [{"moras": [{"vowel": "a", "vowel_length": .30013}], "pause_mora": None}]}).encode()
        stream = io.BytesIO()
        with wave.open(stream, "wb") as wav:
            wav.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 19207)
        return stream.getvalue()


def sample():
    return {"title": "試験", "beats": [{"id": "b", "lines": [{"id": "l", "text": "これは試験です。"}],
              "visuals": [{"kind": "text", "text": "試験"}]}]}


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = FakeVoicevox()
    def tearDown(self):
        self.temp.cleanup()
    def load(self, value):
        write_json(self.root / "project.json", value)
        return load_project(self.root)

    def test_default_single_speaker_and_styles_show_correct_character(self):
        p = self.load(sample())
        result = prepare(self.root, p, self.client)
        self.assertEqual(result["lines"][0]["character"], "zundamon")
        self.assertEqual(result["subtitles"]["font_size"], 68)
        self.assertEqual(result["subtitles"]["inner_outline_width"], 10)
        self.assertEqual(result["subtitles"]["outer_outline_width"], 4)
        self.assertEqual(self.client.identity(1)["character"], "zundamon")
        self.assertEqual(self.client.identity(2)["character"], "metan")
        self.assertIsNone(self.client.identity(8)["character"])
        with self.assertRaises(ValueError): self.client.identity(999)

    def test_speech_cache_tracks_content_voice_settings_and_version(self):
        cache = self.root / "audio"
        for text, voice, settings, expected in [("a", 3, {}, False), ("a", 3, {}, True),
                ("b", 3, {}, False), ("b", 2, {}, False), ("b", 2, {"speedScale": 1.2}, False)]:
            _, reused = synthesize(self.client, cache, text, voice, settings)
            self.assertEqual(reused, expected)
        self.client.version = "test-2"
        record, reused = synthesize(self.client, cache, "b", 2, {"speedScale": 1.2})
        self.assertFalse(reused)
        self.assertIn("query", record)
        self.assertIn("mouth", record)
        Path(record["path"]).write_bytes(b"broken")
        self.assertFalse(synthesize(self.client, cache, "b", 2, {"speedScale": 1.2})[1])

    def test_gap_change_and_reorder_reuse_audio_and_retime_events(self):
        p = sample()
        p["beats"][0]["lines"].append({"id": "l2", "text": "次の発話。"})
        p["beats"][0]["visuals"][0]["from"] = {"line": "l2"}
        first = prepare(self.root, self.load(p), self.client)
        p["beats"][0]["lines"][0]["gap"] = 1.3
        second = prepare(self.root, self.load(p), self.client)
        self.assertEqual(second["speech"], {"generated": 0, "reused": 2})
        self.assertEqual(second["lines"][1]["from"] - first["lines"][1]["from"], 30)
        self.assertEqual(second["beats"][0]["visuals"][0]["from"], second["lines"][1]["from"])
        p["beats"][0]["lines"].reverse()
        third = prepare(self.root, self.load(p), self.client)
        self.assertEqual(third["lines"][0]["id"], "l2")
        self.assertEqual(third["lines"][0]["from"], 0)

    def test_many_short_lines_do_not_accumulate_frame_rounding(self):
        p = sample(); p["beats"][0]["lines"] = [{"id": f"l{i}", "text": "同じ音声", "gap": .013} for i in range(500)]
        result = prepare(self.root, self.load(p), self.client)
        exact = 500 * (19207 / 48000 + .013)
        self.assertLessEqual(abs(result["durationInFrames"] / 30 - exact), 1 / 60)

    def test_bad_ids_voices_and_legacy_fail(self):
        for change in (lambda p: p.update(scenes=[]), lambda p: p["beats"][0]["lines"][0].update(id="b"),
                       lambda p: p["beats"][0]["lines"][0].update(voice="missing"),
                       lambda p: p["beats"][0]["lines"][0].update(gap=-1)):
            p = sample(); change(p)
            with self.assertRaises(ValueError): self.load(p)

    def test_invalid_event_media_and_duration_fail(self):
        for visual in [{"kind": "media", "path": "missing.mp4"}, {"kind": "text", "text": "x", "from": 999},
                       {"kind": "text", "text": "x", "from": {"line": "missing"}}, {"kind": "custom"}]:
            p = sample(); p["beats"][0]["visuals"] = [visual]
            with self.assertRaises(ValueError): prepare(self.root, self.load(p), self.client)
        p = sample(); p["beats"][0]["duration"] = .01
        with self.assertRaises(ValueError): prepare(self.root, self.load(p), self.client)

    def test_short_video_and_audio_are_not_silently_looped(self):
        (self.root / "short.mp4").write_bytes(b"fixture")
        info = {"format": {"duration": ".1"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}
        for key, event in [("visuals", {"kind": "media", "path": "short.mp4"}), ("audio", {"path": "short.mp4"})]:
            p = sample(); p["beats"][0][key] = [event]
            with patch("production.ffprobe", return_value=info), self.assertRaisesRegex(ValueError, "尺"):
                prepare(self.root, self.load(p), self.client)

    def test_dead_worker_is_reported_as_interrupted(self):
        write_json(self.root / "work/job.json", {"status": "running", "pid": 123})
        with patch("video.alive", return_value=False):
            self.assertEqual(state(self.root)["status"], "failed")

    def test_duplicate_build_does_not_spawn(self):
        self.load(sample()); (self.root / "work").mkdir(); (self.root / "work/job.lock").write_text("123")
        write_json(self.root / "work/job.json", {"status": "running", "pid": 123})
        with patch("video.alive", return_value=True), patch("video.subprocess.Popen") as launch:
            self.assertEqual(start(self.root, "final")["status"], "running")
            launch.assert_not_called()

    def test_delivery_rejects_stale_or_unverified_output(self):
        self.load(sample())
        write_json(self.root / "output/final-validation.json", {"passed": True, "project_sha256": "old"})
        with self.assertRaisesRegex(ValueError, "一致"):
            delivery_check(self.root)

    def test_loudness_preserves_real_video_packets_and_trims_audio_padding(self):
        from common import find_executable, run, ffprobe
        ffmpeg = find_executable("ffmpeg")
        if not ffmpeg: self.skipTest("FFmpeg is not installed")
        source, output = self.root / "source.mp4", self.root / "normalized.mp4"
        run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=size=64x64:rate=30:duration=1",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=1.13", "-af", "asetpts=PTS+0.085333/TB", "-c:v", "libx264", "-c:a", "aac", source], capture=True)
        normalize_loudness(source, output, 1)
        info = ffprobe(output)
        self.assertAlmostEqual(float(info["format"]["duration"]), 1, delta=.025)
        hashes = [run([ffmpeg, "-v", "error", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "hash", "-"], capture=True).stdout for path in [source, output]]
        self.assertEqual(hashes[0], hashes[1])

    @unittest.skipUnless(os.name == "nt", "Windows worker containment")
    def test_interrupted_worker_terminates_its_children(self):
        code = "from windows_job import contain_children; import subprocess,sys,time; contain_children(); p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(p.pid,flush=True); time.sleep(30)"
        worker = subprocess.Popen([sys.executable, "-u", "-c", code], cwd=Path(__file__).resolve().parents[1] / "tools", stdout=subprocess.PIPE, text=True)
        try:
            child = int(worker.stdout.readline().strip())
            worker.terminate(); worker.wait(timeout=5)
            from video import alive
            deadline = time.monotonic() + 3
            while alive(child) and time.monotonic() < deadline: time.sleep(.05)
            self.assertFalse(alive(child))
        finally:
            if worker.poll() is None: worker.terminate(); worker.wait(timeout=5)
            worker.stdout.close()


if __name__ == "__main__": unittest.main()
