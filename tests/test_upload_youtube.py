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

    def test_set_thumbnail_uses_official_media_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thumbnail.jpg"
            path.write_bytes(b"\xff\xd8\xffthumbnail")
            response = {"kind": "youtube#thumbnailSetResponse", "items": [{"default": {"url": "https://example.test/t.jpg"}}]}
            with patch.object(
                youtube,
                "http_request",
                return_value=(200, {}, json.dumps(response).encode("utf-8")),
            ) as request_mock:
                self.assertEqual(youtube.set_thumbnail("access", "video-id", path), response)
            method, url = request_mock.call_args.args
            self.assertEqual(method, "POST")
            self.assertIn("/youtube/v3/thumbnails/set?", url)
            self.assertIn("videoId=video-id", url)
            self.assertIn("uploadType=media", url)
            self.assertEqual(request_mock.call_args.kwargs["headers"]["Content-Type"], "image/jpeg")

    def test_changed_thumbnail_hash_requires_only_thumbnail_update(self) -> None:
        manifest = {"thumbnail": {"status": "set", "sha256": "OLD"}}
        self.assertTrue(youtube.thumbnail_is_current(manifest, "OLD"))
        self.assertFalse(youtube.thumbnail_is_current(manifest, "NEW"))

    def test_apply_thumbnail_records_official_api_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.mkdir()
            path = output / "thumbnail.jpg"
            path.write_bytes(b"\xff\xd8\xffnew-thumbnail")
            response = {"kind": "youtube#thumbnailSetResponse", "items": [{"high": {"url": "https://example.test/high.jpg"}}]}
            with patch.object(youtube, "set_thumbnail", return_value=response) as set_mock:
                manifest = youtube.apply_thumbnail("access", "video-id", path, {"processing_status": "succeeded"})
            set_mock.assert_called_once_with("access", "video-id", path)
            self.assertEqual(manifest["status"], "uploaded_and_verified")
            self.assertEqual(manifest["thumbnail"]["status"], "set")
            self.assertEqual(manifest["thumbnail"]["file"], "output/thumbnail.jpg")
            self.assertEqual(manifest["thumbnail"]["api_response"], response)

    def test_forced_thumbnail_update_reapplies_same_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thumbnail.jpg"
            path.write_bytes(b"\xff\xd8\xffsame-thumbnail")
            image_hash = youtube.sha256(path)
            manifest = {"thumbnail": {"status": "set", "sha256": image_hash}}
            response = {"kind": "youtube#thumbnailSetResponse", "items": [{}]}
            with patch.object(youtube, "set_thumbnail", return_value=response) as set_mock:
                youtube.apply_thumbnail("access", "video-id", path, manifest, force=True)
            set_mock.assert_called_once()

    def test_processing_video_is_not_reported_complete_after_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thumbnail.jpg"
            path.write_bytes(b"\xff\xd8\xffimage")
            with patch.object(youtube, "set_thumbnail", return_value={"items": [{}]}):
                manifest = youtube.apply_thumbnail("access", "id", path, {"processing_status": "processing"})
            self.assertEqual(manifest["status"], "uploaded_processing")
            with patch.object(youtube, "set_thumbnail") as upload:
                self.assertEqual(youtube.apply_thumbnail("access", "id", path, manifest)["status"], "uploaded_processing")
                upload.assert_not_called()

    def test_same_video_reuses_remote_identity_and_different_video_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "youtube-upload.json"
            path.write_text(json.dumps({"video_id": "saved", "sha256": "same"}), encoding="utf-8")
            remote = {"id": "saved", "snippet": {"title": "試験"}, "status": {"privacyStatus": "private"}, "processingDetails": {"processingStatus": "succeeded"}}
            with patch.object(youtube, "get_video", return_value=remote) as get:
                result = youtube.existing_verified_upload(path, "same", "access", "試験")
                self.assertEqual(result["video_id"], "saved")
                get.assert_called_once()
            with patch.object(youtube, "get_video") as get:
                self.assertIsNone(youtube.existing_verified_upload(path, "changed", "access", "試験"))
                get.assert_not_called()

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
