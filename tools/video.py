"""One local CLI. Editorial choices live in project.json, never in the worker."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from common import REPO_ROOT, ffprobe, final_output_path, find_executable, read_json, run, write_json
from production import load_project, prepare, validate_output, validate_thumbnail, normalize_loudness


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def state(root: Path) -> dict:
    path = root / "work" / "job.json"
    try:
        result = read_json(path)
    except (OSError, ValueError):
        return {"status": "not_started"}
    if result.get("status") in {"starting", "running"} and not alive(result.get("pid", 0)):
        result.update(status="failed", error="処理が中断されました。buildで再実行できます")
        write_json(path, result)
    return {k: v for k, v in result.items() if k != "pid"}


def start(root: Path, quality: str) -> dict:
    load_project(root)
    work = root / "work"
    work.mkdir(parents=True, exist_ok=True)
    lock = work / "job.lock"
    if lock.exists():
        try:
            owner = int(lock.read_text())
        except (ValueError, OSError):
            owner = 0
        if owner and alive(owner):
            return {**state(root), "message": "この案件の処理は実行中です"}
        lock.unlink(missing_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {"status": "starting"}
    with os.fdopen(descriptor, "w") as stream:
        stream.write(str(os.getpid()))
    write_json(work / "job.json", {"status": "starting", "quality": quality, "pid": os.getpid()})
    try:
        with (work / "job.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_worker", str(root), "--quality", quality],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=REPO_ROOT,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        lock.write_text(str(process.pid))
        return {"status": "started", "quality": quality, "log": str(work / "job.log")}
    except Exception:
        lock.unlink(missing_ok=True)
        raise


def run_worker(root: Path, quality: str) -> int:
    work = root / "work"
    started = time.monotonic()
    record = {"status": "running", "quality": quality, "pid": os.getpid(), "stage": "speech", "log": str(work / "job.log")}
    write_json(work / "job.json", record)
    try:
        from windows_job import contain_children
        contain_children()
        project = load_project(root)
        project_hash = hashlib.sha256((root / "project.json").read_bytes()).hexdigest()
        (root / "output").mkdir(parents=True, exist_ok=True)
        # Invalidate success before any work; a failed retry must not authorize delivery.
        (root / "output" / f"{quality}-validation.json").unlink(missing_ok=True)
        timing = prepare(root, project)
        record.update(stage="render", **timing["speech"])
        write_json(work / "job.json", record)
        output = root / "output" / "preview.mp4" if quality == "preview" else final_output_path(root, project)
        temporary = work / f"{quality}.mp4"
        rendered = work / f"{quality}-rendered.mp4"
        node = find_executable("node")
        if not node:
            raise RuntimeError("Node.jsが見つかりません")
        subprocess.run([str(node), str(REPO_ROOT / "remotion" / "render.mjs"), str(root), str(rendered), quality], check=True, cwd=REPO_ROOT / "remotion")
        record.update(stage="loudness")
        write_json(work / "job.json", record)
        normalize_loudness(rendered, temporary, timing["durationInFrames"] / timing["video"]["fps"])
        if hashlib.sha256((root / "project.json").read_bytes()).hexdigest() != project_hash:
            raise ValueError("制作中にproject.jsonが変更されました。buildを再実行してください")
        record.update(stage="verify")
        write_json(work / "job.json", record)
        result = validate_output(root, project, timing, temporary, quality)
        temporary.replace(output)
        result.update(file=output.relative_to(root).as_posix(), project_sha256=project_hash)
        write_json(root / "output" / f"{quality}-validation.json", result)
        record.update(status="succeeded", stage="complete", output=str(output), duration=result["duration"], elapsed_seconds=round(time.monotonic() - started, 1))
        return 0
    except Exception as exc:
        traceback.print_exc()
        record.update(status="failed", error=str(exc).splitlines()[0][:240])
        (root / "output" / f"{quality}-validation.json").unlink(missing_ok=True)
        return 1
    finally:
        write_json(work / "job.json", record)
        (work / "job.lock").unlink(missing_ok=True)


def delivery_check(root: Path) -> None:
    if state(root).get("status") in {"starting", "running"}:
        raise ValueError("制作中のため納品できません")
    project = load_project(root)
    receipt = read_json(root / "output" / "final-validation.json")
    output = final_output_path(root, project)
    if (receipt.get("passed") is not True or receipt.get("project_sha256") != hashlib.sha256((root / "project.json").read_bytes()).hexdigest()
            or receipt.get("sha256") != hashlib.sha256(output.read_bytes()).hexdigest()):
        raise ValueError("完成版の検証結果が現在の台本・動画と一致しません。build --quality finalを実行してください")
    validate_thumbnail(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codexの台本と演出をローカルで動画化します")
    parser.add_argument("command", choices=["check", "build", "status", "wait", "inspect", "deliver", "_worker"])
    parser.add_argument("project", type=Path, nargs="?")
    parser.add_argument("--quality", choices=["preview", "final"], default="preview")
    parser.add_argument("--timeout", type=float, default=55)
    parser.add_argument("--at", type=float, default=0)
    parser.add_argument("--duration", type=float, default=0)
    parser.add_argument("--voices", action="store_true", help="check時にVOICEVOXの声一覧を表示")
    args = parser.parse_args()
    root = args.project.resolve() if args.project else None
    if args.command == "check":
        from speech import Voicevox
        client = Voicevox()
        for name in ("node", "ffmpeg", "ffprobe"):
            if not find_executable(name):
                raise ValueError(f"{name}が見つかりません")
        if root:
            project = load_project(root)
            for voice in project["voices"].values():
                client.identity(voice["style_id"])
        if not (REPO_ROOT / "remotion/node_modules/@remotion/renderer/package.json").is_file():
            raise ValueError("npm ci --prefix remotion を実行してください")
        emit({"ready": True, "voicevox": client.version, **({"voices": [{"name": v["name"], "styles": v["styles"]} for v in client.voices]} if args.voices else {})})
        return 0
    if root is None:
        parser.error("projectディレクトリが必要です")
    if args.command == "_worker":
        return run_worker(root, args.quality)
    if args.command == "build":
        emit(start(root, args.quality))
    elif args.command in {"status", "wait"}:
        deadline = time.monotonic() + min(55, max(0, args.timeout)) if args.command == "wait" else 0
        while True:
            result = state(root)
            if result["status"] not in {"starting", "running"} or time.monotonic() >= deadline:
                break
            time.sleep(1)
        emit(result)
        return int(result["status"] == "failed")
    elif args.command == "inspect":
        project = load_project(root)
        output = root / "output" / "preview.mp4" if args.quality == "preview" else final_output_path(root, project)
        if args.at < 0 or args.duration < 0:
            raise ValueError("atとdurationは0以上にしてください")
        duration = float(ffprobe(output)["format"]["duration"])
        if args.at >= duration or args.at + args.duration > duration:
            raise ValueError("確認区間が動画の範囲外です")
        target = root / "work" / (f"inspect-{args.at:g}.mp4" if args.duration else f"inspect-{args.at:g}.png")
        command = [find_executable("ffmpeg"), "-v", "error", "-y", "-ss", str(args.at), "-i", output]
        command += ["-t", str(args.duration)] if args.duration else ["-frames:v", "1"]
        run([*command, target], capture=True)
        emit({"output": str(target)})
    elif args.command == "deliver":
        delivery_check(root)
        run([sys.executable, REPO_ROOT / "tools" / "upload_youtube.py", root])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        emit({"status": "failed", "error": str(exc).splitlines()[0][:240]})
        raise SystemExit(1)
