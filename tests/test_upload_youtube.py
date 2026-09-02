from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import upload_youtube as youtube


class YouTubeUploadTests(unittest.TestCase):
    def test_build_video_resource_is_always_private(self) -> None:
        project = {
            "title": "テスト動画",
            "youtube": {
                "description": "説明",
                "tags": ["テスト", "動画"],
                "category_id": "28",
                "made_for_kids": True,
                "privacy_status": "public",
            },
        }
        resource = youtube.build_video_resource(project, {"youtube": {"category_id": "22"}})
        self.assertEqual(resource["snippet"]["title"], "テスト動画")
        self.assertEqual(resource["snippet"]["categoryId"], "28")
        self.assertEqual(resource["status"]["privacyStatus"], "private")
        self.assertTrue(resource["status"]["selfDeclaredMadeForKids"])

    def test_load_client_credentials_from_google_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oauth.json"
            path.write_text(
                json.dumps({"installed": {"client_id": "client-id", "client_secret": "client-secret"}}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    youtube.load_client_credentials(path),
                    ("client-id", "client-secret"),
                )

    def test_partial_environment_credentials_are_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"YOUTUBE_CLIENT_ID": "client-id", "YOUTUBE_CLIENT_SECRET": ""},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "両方"):
                youtube.load_client_credentials()

    def test_range_header_to_next_offset(self) -> None:
        self.assertEqual(youtube._next_offset(None), 0)
        self.assertEqual(youtube._next_offset("bytes=0-1048575"), 1048576)

    def test_made_for_kids_must_be_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "trueまたはfalse"):
            youtube.build_video_resource(
                {"title": "テスト", "youtube": {"made_for_kids": "false"}},
                {"youtube": {}},
            )

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
    def test_refresh_token_is_dpapi_encrypted_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.json"
            youtube.save_refresh_token(path, "secret-refresh-token")
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("secret-refresh-token", raw)
            self.assertEqual(youtube.load_refresh_token(path), "secret-refresh-token")


if __name__ == "__main__":
    unittest.main()
