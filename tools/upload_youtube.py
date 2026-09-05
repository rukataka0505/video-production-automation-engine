from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from common import REPO_ROOT, final_output_path, read_json, write_json


DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
THUMBNAILS_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
PRIVACY_STATUS = "private"
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
RIGHTS_WARNING = (
    "この動画は個人利用を前提として生成されています。Web上から取得した画像・動画・音声・PDF・"
    "文書内の図表等が含まれる可能性があり、個人利用の制作では権利関係や再利用ライセンスが明確であることを"
    "素材採用の必須条件としていません。YouTube、SNS、Web等で公開・配布・商用利用する場合は、"
    "使用素材の著作権・ライセンス・利用条件を確認してください。"
)


class YouTubeError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload

    @property
    def oauth_error(self) -> str:
        return str(self.payload.get("error", "")) if isinstance(self.payload, dict) else ""


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def local_config_dir() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / "VideoAutomationEngine"


def default_client_secrets_path() -> Path:
    return local_config_dir() / "youtube-client-secret.json"


def default_token_path() -> Path:
    configured = os.environ.get("YOUTUBE_TOKEN_FILE", "").strip()
    return Path(configured).expanduser() if configured else local_config_dir() / "youtube-oauth-token.json"


def _dpapi_encrypt(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("OAuthトークンの保存にはWindows DPAPIが必要です")
    raw = value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    encrypted = DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "VideoAutomationEngine YouTube OAuth",
        None,
        None,
        None,
        0x01,
        ctypes.byref(encrypted),
    ):
        raise ctypes.WinError()
    try:
        protected = ctypes.string_at(encrypted.pbData, encrypted.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(encrypted.pbData)


def _dpapi_decrypt(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("OAuthトークンの読込にはWindows DPAPIが必要です")
    raw = base64.b64decode(value, validate=True)
    buffer = ctypes.create_string_buffer(raw)
    source = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    decrypted = DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(decrypted)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(decrypted.pbData, decrypted.cbData).decode("utf-8")
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(decrypted.pbData)


def load_refresh_token(path: Path) -> str | None:
    if not path.is_file():
        return None
    payload = read_json(path)
    if payload.get("storage") != "windows-dpapi-current-user-v1" or not payload.get("refresh_token"):
        raise RuntimeError(f"未対応または壊れたYouTubeトークンファイルです: {path}")
    return _dpapi_decrypt(str(payload["refresh_token"]))


def save_refresh_token(path: Path, refresh_token: str) -> None:
    if not refresh_token:
        raise ValueError("空のrefresh tokenは保存できません")
    payload = {
        "storage": "windows-dpapi-current-user-v1",
        "refresh_token": _dpapi_encrypt(refresh_token),
        "scope": YOUTUBE_SCOPE,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_json(path, payload)


def _credential_record(payload: dict[str, Any], source: str) -> tuple[str, str]:
    record = payload.get("installed") or payload.get("web") or payload
    if not isinstance(record, dict):
        raise RuntimeError(f"Google OAuthクライアントJSONの形式が不正です: {source}")
    client_id = str(record.get("client_id", "")).strip()
    client_secret = str(record.get("client_secret", "")).strip()
    if not client_id or not client_secret:
        raise RuntimeError(f"client_idまたはclient_secretがありません: {source}")
    return client_id, client_secret


def load_client_credentials(explicit_path: Path | None = None) -> tuple[str, str]:
    if explicit_path is not None:
        path = explicit_path.expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Google OAuthクライアントJSONがありません: {path}")
        return _credential_record(read_json(path), str(path))

    env_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    env_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    if env_id or env_secret:
        if not env_id or not env_secret:
            raise RuntimeError("YOUTUBE_CLIENT_IDとYOUTUBE_CLIENT_SECRETは両方設定してください")
        return env_id, env_secret

    configured = os.environ.get("YOUTUBE_CLIENT_SECRETS_FILE", "").strip()
    path = Path(configured).expanduser() if configured else default_client_secrets_path()
    if not path.is_file():
        raise FileNotFoundError(
            "YouTube OAuthクライアント情報がありません。Google Cloudで「テレビと入力が限られたデバイス」の"
            f"OAuthクライアントJSONを作り、{default_client_secrets_path()} に保存するか、"
            "YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRETを設定してください。"
        )
    return _credential_record(read_json(path), str(path))


def install_client_secrets(source: Path) -> Path:
    source = source.expanduser().resolve()
    _credential_record(read_json(source), str(source))
    target = default_client_secrets_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source != target.resolve():
        shutil.copyfile(source, target)
    print(f"OAuthクライアント情報をリポジトリ外へ保存しました: {target}")
    return target


def _decode_json(body: bytes) -> Any:
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": body.decode("utf-8", errors="replace")}


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 60,
    accepted: set[int] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    accepted = accepted or {200}
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            body = response.read()
            response_headers = dict(response.headers.items())
    except HTTPError as exc:
        status = int(exc.code)
        body = exc.read()
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        if status in accepted:
            return status, response_headers, body
        payload = _decode_json(body)
        message = payload.get("error_description") if isinstance(payload, dict) else None
        if not message and isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            message = payload["error"].get("message")
        if not message:
            message = str(payload)
        raise YouTubeError(f"Google API HTTP {status}: {message}", status=status, payload=payload) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise YouTubeError(f"Google APIへの接続に失敗しました: {exc}") from exc
    if status not in accepted:
        raise YouTubeError(f"Google APIが予期しないHTTP {status}を返しました", status=status, payload=_decode_json(body))
    return status, response_headers, body


def post_form(url: str, values: dict[str, str], *, accepted: set[int] | None = None) -> dict[str, Any]:
    data = urlencode(values).encode("ascii")
    _, _, body = http_request(
        "POST",
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        accepted=accepted or {200},
    )
    payload = _decode_json(body)
    if not isinstance(payload, dict):
        raise YouTubeError("Google OAuth応答の形式が不正です", payload=payload)
    return payload


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    return post_form(
        TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )


def authorize_device(client_id: str, client_secret: str) -> dict[str, Any]:
    device = post_form(DEVICE_CODE_URL, {"client_id": client_id, "scope": YOUTUBE_SCOPE})
    device_code = str(device.get("device_code", ""))
    user_code = str(device.get("user_code", ""))
    verification_url = str(device.get("verification_url") or device.get("verification_uri") or "")
    if not device_code or not user_code or not verification_url:
        raise YouTubeError("Device Authorization応答にURLまたはコードがありません", payload=device)

    print("\nYouTubeの再認証が必要です。スマホのブラウザで次を開いてください。", flush=True)
    print(f"認証URL: {verification_url}", flush=True)
    print(f"コード: {user_code}", flush=True)
    print("認証完了を待っています…", flush=True)

    interval = max(1, int(device.get("interval", 5)))
    deadline = time.monotonic() + int(device.get("expires_in", 1800))
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            token = post_form(
                TOKEN_URL,
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "device_code": device_code,
                    "grant_type": DEVICE_GRANT_TYPE,
                },
            )
            if token.get("access_token") and token.get("refresh_token"):
                print("YouTubeの認証が完了しました。", flush=True)
                return token
            raise YouTubeError("認証成功応答に必要なトークンがありません", payload=token)
        except YouTubeError as exc:
            if exc.oauth_error == "authorization_pending":
                continue
            if exc.oauth_error == "slow_down":
                interval += 5
                continue
            if exc.oauth_error == "access_denied":
                raise RuntimeError("スマホ側でYouTubeへのアクセスが拒否されました") from exc
            if exc.oauth_error == "expired_token":
                raise RuntimeError("再認証コードの有効期限が切れました。もう一度実行してください") from exc
            raise
    raise RuntimeError("再認証コードの有効期限が切れました。もう一度実行してください")


def obtain_access_token(
    client_id: str, client_secret: str, token_path: Path, *, force_reauth: bool = False
) -> str:
    if not force_reauth:
        refresh_token = load_refresh_token(token_path)
        if refresh_token:
            try:
                refreshed = refresh_access_token(client_id, client_secret, refresh_token)
                access_token = str(refreshed.get("access_token", ""))
                if not access_token:
                    raise YouTubeError("refresh応答にaccess tokenがありません", payload=refreshed)
                return access_token
            except YouTubeError as exc:
                if exc.oauth_error != "invalid_grant":
                    raise
                print("保存済みのYouTube認証が失効しました。新しい認証を開始します。", flush=True)

    token = authorize_device(client_id, client_secret)
    save_refresh_token(token_path, str(token["refresh_token"]))
    return str(token["access_token"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def thumbnail_path(project_dir: Path) -> Path:
    return project_dir.resolve() / "output" / "thumbnail.jpg"


def set_thumbnail(access_token: str, video_id: str, image_path: Path) -> dict[str, Any]:
    if not image_path.is_file():
        raise FileNotFoundError(f"サムネイルがありません: {image_path}")
    if image_path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError("YouTubeサムネイルはJPEGにしてください")
    data = image_path.read_bytes()
    if not data.startswith(b"\xff\xd8\xff"):
        raise ValueError(f"サムネイルが有効なJPEGではありません: {image_path}")
    query = urlencode({"videoId": video_id, "uploadType": "media"})
    _, _, body = http_request(
        "POST",
        f"{THUMBNAILS_UPLOAD_URL}?{query}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "image/jpeg",
            "Content-Length": str(len(data)),
        },
        data=data,
        timeout=300,
        accepted={200},
    )
    payload = _decode_json(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or not payload["items"]:
        raise YouTubeError("サムネイル設定の完了応答が不正です", payload=payload)
    return payload


def thumbnail_is_current(manifest: dict[str, Any], image_hash: str) -> bool:
    thumbnail = manifest.get("thumbnail")
    return (
        isinstance(thumbnail, dict)
        and thumbnail.get("status") == "set"
        and thumbnail.get("sha256") == image_hash
    )


def apply_thumbnail(
    access_token: str,
    video_id: str,
    image_path: Path,
    manifest: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    image_hash = sha256(image_path)
    if not force and thumbnail_is_current(manifest, image_hash):
        manifest["status"] = "uploaded_and_verified" if manifest.get("processing_status") == "succeeded" else "uploaded_processing"
        return manifest
    response = set_thumbnail(access_token, video_id, image_path)
    manifest["thumbnail"] = {
        "status": "set",
        "file": "output/thumbnail.jpg" if image_path.parent.name == "output" else str(image_path),
        "size_bytes": image_path.stat().st_size,
        "sha256": image_hash,
        "set_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api_response": response,
    }
    manifest["status"] = "uploaded_and_verified" if manifest.get("processing_status") == "succeeded" else "uploaded_processing"
    return manifest


def build_video_resource(project: dict[str, Any], style: dict[str, Any]) -> dict[str, Any]:
    youtube = project.get("youtube", {})
    defaults = style.get("youtube", {})
    title = str(youtube.get("title") or project.get("title") or "").strip()
    if not title:
        raise ValueError("YouTubeタイトルがありません")
    if len(title) > 100:
        raise ValueError("YouTubeタイトルは100文字以内にしてください")
    description = str(youtube.get("description", ""))
    if len(description.encode("utf-8")) > 5000:
        raise ValueError("YouTube概要欄が長すぎます")
    tags = youtube.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        raise ValueError("youtube.tagsは空でない文字列の配列にしてください")
    category_id = str(youtube.get("category_id") or defaults.get("category_id") or "22")
    made_for_kids = youtube.get("made_for_kids", defaults.get("made_for_kids", False))
    if not isinstance(made_for_kids, bool):
        raise ValueError("youtube.made_for_kidsはtrueまたはfalseにしてください")
    snippet: dict[str, Any] = {"title": title, "description": description, "categoryId": category_id}
    if tags:
        snippet["tags"] = tags
    return {
        "snippet": snippet,
        "status": {
            "privacyStatus": PRIVACY_STATUS,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }


def start_resumable_upload(access_token: str, video_path: Path, resource: dict[str, Any]) -> str:
    body = json.dumps(resource, ensure_ascii=False).encode("utf-8")
    content_type = mimetypes.guess_type(video_path.name)[0] or "application/octet-stream"
    _, headers, _ = http_request(
        "POST",
        f"{UPLOAD_URL}?{urlencode({'uploadType': 'resumable', 'part': 'snippet,status'})}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(video_path.stat().st_size),
            "X-Upload-Content-Type": content_type,
        },
        data=body,
        accepted={200},
    )
    location = headers.get("Location") or headers.get("location")
    if not location:
        raise YouTubeError("再開可能アップロードURLが返されませんでした")
    return location


def _next_offset(range_header: str | None) -> int:
    if not range_header:
        return 0
    match = re.search(r"(?:bytes=)?\d+-(\d+)$", range_header.strip())
    if not match:
        raise YouTubeError(f"YouTubeのRange応答が不正です: {range_header}")
    return int(match.group(1)) + 1


def query_upload_offset(session_url: str, access_token: str, total_size: int) -> tuple[int, dict[str, Any] | None]:
    status, headers, body = http_request(
        "PUT",
        session_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Length": "0",
            "Content-Range": f"bytes */{total_size}",
        },
        data=b"",
        timeout=60,
        accepted={200, 201, 308},
    )
    if status in {200, 201}:
        result = _decode_json(body)
        return total_size, result if isinstance(result, dict) else None
    return _next_offset(headers.get("Range") or headers.get("range")), None


def upload_file(
    session_url: str,
    access_token: str,
    video_path: Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_retries: int = 8,
) -> dict[str, Any]:
    if chunk_size <= 0 or chunk_size % (256 * 1024):
        raise ValueError("チャンクサイズは256KBの倍数にしてください")
    total = video_path.stat().st_size
    offset = 0
    retries = 0
    content_type = mimetypes.guess_type(video_path.name)[0] or "application/octet-stream"
    with video_path.open("rb") as source:
        while offset < total:
            source.seek(offset)
            chunk = source.read(min(chunk_size, total - offset))
            last = offset + len(chunk) - 1
            try:
                status, headers, body = http_request(
                    "PUT",
                    session_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": content_type,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{last}/{total}",
                    },
                    data=chunk,
                    timeout=300,
                    accepted={200, 201, 308},
                )
                retries = 0
                if status in {200, 201}:
                    result = _decode_json(body)
                    if not isinstance(result, dict) or not result.get("id"):
                        raise YouTubeError("アップロード完了応答に動画IDがありません", payload=result)
                    print("アップロード: 100.0%", flush=True)
                    return result
                offset = _next_offset(headers.get("Range") or headers.get("range"))
                print(f"アップロード: {offset / total * 100:.1f}%", flush=True)
            except YouTubeError as exc:
                if exc.status not in RETRIABLE_STATUS_CODES and exc.status is not None:
                    raise
                retries += 1
                if retries > max_retries:
                    raise RuntimeError("YouTubeアップロードの再試行上限を超えました") from exc
                delay = min(2 ** retries, 60)
                print(f"通信を再確認します（{delay}秒後、{retries}/{max_retries}）", flush=True)
                time.sleep(delay)
                offset, complete = query_upload_offset(session_url, access_token, total)
                if complete and complete.get("id"):
                    return complete
    raise RuntimeError("YouTubeアップロードが完了しませんでした")


def get_video(access_token: str, video_id: str) -> dict[str, Any]:
    query = urlencode({"part": "snippet,status,processingDetails", "id": video_id})
    _, _, body = http_request(
        "GET",
        f"{VIDEOS_URL}?{query}",
        headers={"Authorization": f"Bearer {access_token}"},
        accepted={200},
    )
    payload = _decode_json(body)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if len(items) != 1:
        raise YouTubeError(f"アップロード済み動画を再取得できません: {video_id}", payload=payload)
    return items[0]


def wait_for_processing(access_token: str, video_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        video = get_video(access_token, video_id)
        status = str(video.get("processingDetails", {}).get("processingStatus", "unknown"))
        print(f"YouTube処理状態: {status}", flush=True)
        if status in {"succeeded", "failed", "terminated"}:
            if status != "succeeded":
                raise RuntimeError(f"YouTube側の動画処理が失敗しました: {status}")
            return video
        if time.monotonic() >= deadline:
            raise TimeoutError(f"YouTube側の動画処理が{timeout_seconds}秒以内に完了しませんでした")
        time.sleep(15)


def verify_video(video: dict[str, Any], expected_title: str) -> None:
    actual_title = str(video.get("snippet", {}).get("title", ""))
    privacy = str(video.get("status", {}).get("privacyStatus", ""))
    if actual_title != expected_title:
        raise RuntimeError(f"YouTube上のタイトルが不一致です: {actual_title}")
    if privacy != PRIVACY_STATUS:
        raise RuntimeError(f"YouTube動画が非公開ではありません: {privacy}")


def existing_verified_upload(
    manifest_path: Path, file_hash: str, access_token: str, expected_title: str
) -> dict[str, Any] | None:
    if not manifest_path.is_file():
        return None
    manifest = read_json(manifest_path)
    if manifest.get("sha256") != file_hash or not manifest.get("video_id"):
        return None
    video = get_video(access_token, str(manifest["video_id"]))
    verify_video(video, expected_title)
    manifest.update(
        {
            "status": "video_verified_thumbnail_pending",
            "privacy_status": PRIVACY_STATUS,
            "processing_status": video.get("processingDetails", {}).get("processingStatus", "unknown"),
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="検証済み完成動画をYouTubeへ必ず非公開でアップロードします")
    parser.add_argument("project_dir", nargs="?", type=Path)
    parser.add_argument("--client-secrets", type=Path, help="Google OAuthクライアントJSONのパス")
    parser.add_argument(
        "--install-client-secrets",
        type=Path,
        help="Google OAuthクライアントJSONを既定のリポジトリ外設定先へコピー",
    )
    parser.add_argument("--auth-only", action="store_true", help="Device Flow認証だけを実行")
    parser.add_argument("--force-reauth", action="store_true", help="保存済みrefresh tokenを使わず再認証")
    parser.add_argument("--force-upload", action="store_true", help="同じ動画の確認済み記録があっても再アップロード")
    parser.add_argument(
        "--thumbnail-only",
        action="store_true",
        help="既存のYouTube動画へoutput/thumbnail.jpgだけを再設定",
    )
    parser.add_argument("--no-wait-processing", action="store_true", help="YouTube側の処理完了を待たない")
    parser.add_argument("--processing-timeout", type=int, default=1800)
    args = parser.parse_args()

    installed_path = install_client_secrets(args.install_client_secrets) if args.install_client_secrets else None
    client_id, client_secret = load_client_credentials(installed_path or args.client_secrets)
    token_path = default_token_path()
    access_token = obtain_access_token(client_id, client_secret, token_path, force_reauth=args.force_reauth)
    if args.auth_only:
        print(f"認証情報を確認しました。暗号化トークン: {token_path}")
        return 0
    if not args.project_dir:
        parser.error("アップロード時はproject_dirが必要です")
    if args.thumbnail_only and args.force_upload:
        parser.error("--thumbnail-onlyと--force-uploadは同時に指定できません")

    project_dir = args.project_dir.resolve()
    project = read_json(project_dir / "project.json")
    style = read_json(REPO_ROOT / "style.json")
    image_path = thumbnail_path(project_dir)
    if not image_path.is_file():
        raise FileNotFoundError(f"サムネイルがありません: {image_path}")
    resource = build_video_resource(project, style)
    expected_title = str(resource["snippet"]["title"])
    manifest_path = project_dir / "output" / "youtube-upload.json"

    if args.thumbnail_only:
        if not manifest_path.is_file():
            raise RuntimeError("既存動画のyoutube-upload.jsonがないため、サムネイルだけを設定できません")
        manifest = read_json(manifest_path)
        video_id = str(manifest.get("video_id", "")).strip()
        if not video_id:
            raise RuntimeError("youtube-upload.jsonに既存の動画IDがありません")
        verified = get_video(access_token, video_id)
        verify_video(verified, expected_title)
        manifest.update(
            {
                "status": "video_verified_thumbnail_pending",
                "privacy_status": PRIVACY_STATUS,
                "processing_status": verified.get("processingDetails", {}).get("processingStatus", "unknown"),
                "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        manifest = apply_thumbnail(access_token, video_id, image_path, manifest, force=True)
        write_json(manifest_path, manifest)
        print("既存のYouTube動画へサムネイルだけを設定しました。")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    from video import delivery_check
    delivery_check(project_dir)
    video_path = final_output_path(project_dir, project)
    if not video_path.is_file():
        raise FileNotFoundError(f"完成動画がありません: {video_path}")
    file_hash = sha256(video_path)

    if not args.force_upload:
        existing = existing_verified_upload(manifest_path, file_hash, access_token, expected_title)
        if existing:
            if not args.no_wait_processing and existing.get("processing_status") != "succeeded":
                verified = wait_for_processing(access_token, str(existing["video_id"]), args.processing_timeout)
                verify_video(verified, expected_title)
                existing["processing_status"] = "succeeded"
                existing["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            thumbnail_changed = not thumbnail_is_current(existing, sha256(image_path))
            existing = apply_thumbnail(access_token, str(existing["video_id"]), image_path, existing)
            write_json(manifest_path, existing)
            if thumbnail_changed:
                print("同一動画を再アップロードせず、変更されたサムネイルだけを設定しました。")
            else:
                print("同一動画とサムネイルは設定済みです。YouTube側を再確認しました。")
            print(json.dumps(existing, ensure_ascii=False, indent=2))
            return 0

    session_url = start_resumable_upload(access_token, video_path, resource)
    uploaded = upload_file(session_url, access_token, video_path)
    video_id = str(uploaded["id"])
    pending_manifest = {
        "status": "uploaded_processing",
        "video_id": video_id,
        "watch_url": f"https://www.youtube.com/watch?v={video_id}",
        "privacy_status": PRIVACY_STATUS,
        "processing_status": "unknown",
        "title": expected_title,
        "file": video_path.relative_to(project_dir).as_posix(),
        "size_bytes": video_path.stat().st_size,
        "sha256": file_hash,
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rights_warning": RIGHTS_WARNING,
    }
    write_json(manifest_path, pending_manifest)
    if args.no_wait_processing:
        verified = get_video(access_token, video_id)
    else:
        verified = wait_for_processing(access_token, video_id, args.processing_timeout)
    verify_video(verified, expected_title)
    manifest = {
        **pending_manifest,
        "status": "video_verified_thumbnail_pending",
        "processing_status": verified.get("processingDetails", {}).get("processingStatus", "unknown"),
        "title": verified.get("snippet", {}).get("title"),
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_json(manifest_path, manifest)
    manifest = apply_thumbnail(access_token, video_id, image_path, manifest)
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError, YouTubeError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        raise SystemExit(1)
