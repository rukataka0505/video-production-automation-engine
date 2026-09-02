from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RENDER_SCRIPT = Path(__file__).with_name("render_video.py")
TERMINAL_STATUSES = {"succeeded", "failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_paths(project_dir: Path, quality: str) -> dict[str, Path]:
    root = project_dir.resolve() / "work" / "render-jobs"
    return {
        "root": root,
        "state": root / f"{quality}.json",
        "lock": root / f"{quality}.lock",
        "log": root / f"{quality}.log",
        "result": root / f"{quality}-result.json",
    }


def read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "not_started"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"status": "unknown"}


def write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def process_is_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def compact_state(state: dict[str, Any]) -> dict[str, Any]:
    keys = ("status", "quality", "output", "duration", "reused", "started_at", "finished_at", "log")
    return {key: state[key] for key in keys if key in state}


def print_state(state: dict[str, Any]) -> None:
    print(json.dumps(compact_state(state), ensure_ascii=False))


def release_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def start_job(project_dir: Path, quality: str, no_subtitles: bool, force: bool) -> int:
    project_dir = project_dir.resolve()
    if not (project_dir / "project.json").is_file():
        raise FileNotFoundError(f"project.jsonがありません: {project_dir}")
    paths = job_paths(project_dir, quality)
    paths["root"].mkdir(parents=True, exist_ok=True)
    state = read_state(paths["state"])
    if paths["lock"].exists():
        if state.get("status") == "starting" or (
            state.get("status") == "running" and process_is_running(state.get("pid"))
        ):
            print_state(state)
            return 0
        release_lock(paths["lock"])

    try:
        descriptor = os.open(paths["lock"], os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
    except FileExistsError:
        print_state(read_state(paths["state"]))
        return 0

    starting = {
        "status": "starting",
        "quality": quality,
        "started_at": utc_now(),
        "log": str(paths["log"]),
    }
    write_state(paths["state"], starting)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_worker",
        str(project_dir),
        "--quality",
        quality,
    ]
    if no_subtitles:
        command.append("--no-subtitles")
    if force:
        command.append("--force")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        with paths["log"].open("w", encoding="utf-8") as log:
            subprocess.Popen(
                command,
                cwd=str(RENDER_SCRIPT.parents[1]),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
            )
    except Exception:
        write_state(
            paths["state"],
            {**starting, "status": "failed", "finished_at": utc_now()},
        )
        release_lock(paths["lock"])
        raise
    print_state({"status": "started", "quality": quality, "started_at": starting["started_at"]})
    return 0


def run_worker(project_dir: Path, quality: str, no_subtitles: bool, force: bool) -> int:
    project_dir = project_dir.resolve()
    paths = job_paths(project_dir, quality)
    started_at = utc_now()
    state = {
        "status": "running",
        "quality": quality,
        "pid": os.getpid(),
        "started_at": started_at,
        "log": str(paths["log"]),
    }
    write_state(paths["state"], state)
    command = [
        sys.executable,
        str(RENDER_SCRIPT),
        str(project_dir),
        "--quality",
        quality,
        "--result-file",
        str(paths["result"]),
    ]
    if no_subtitles:
        command.append("--no-subtitles")
    if force:
        command.append("--force")
    try:
        try:
            paths["result"].unlink()
        except FileNotFoundError:
            pass
        completed = subprocess.run(command, cwd=str(RENDER_SCRIPT.parents[1]), check=False)
        if completed.returncode == 0 and paths["result"].is_file():
            result = json.loads(paths["result"].read_text(encoding="utf-8"))
            state.update(
                {
                    "status": "succeeded",
                    "output": result.get("output"),
                    "duration": result.get("duration"),
                    "reused": bool(result.get("reused")),
                    "finished_at": utc_now(),
                }
            )
        else:
            state.update({"status": "failed", "exit_code": completed.returncode, "finished_at": utc_now()})
    except Exception as error:
        state.update({"status": "failed", "error": type(error).__name__, "finished_at": utc_now()})
    finally:
        write_state(paths["state"], state)
        release_lock(paths["lock"])
    return 0 if state["status"] == "succeeded" else 1


def current_state(project_dir: Path, quality: str) -> dict[str, Any]:
    paths = job_paths(project_dir, quality)
    state = read_state(paths["state"])
    if state.get("status") == "running" and not process_is_running(state.get("pid")):
        state.update({"status": "failed", "finished_at": utc_now(), "log": str(paths["log"])})
        write_state(paths["state"], state)
        release_lock(paths["lock"])
    return state


def wait_for_job(project_dir: Path, quality: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        state = current_state(project_dir, quality)
        if state.get("status") in TERMINAL_STATUSES or time.monotonic() >= deadline:
            return state
        time.sleep(1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="レンダーを静かに起動し、状態だけを確認します")
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("start", "_worker"):
        command = subparsers.add_parser(action)
        command.add_argument("project_dir", type=Path)
        command.add_argument("--quality", choices=("preview", "final"), default="preview")
        command.add_argument("--no-subtitles", action="store_true")
        command.add_argument("--force", action="store_true")
    status = subparsers.add_parser("status")
    status.add_argument("project_dir", type=Path)
    status.add_argument("--quality", choices=("preview", "final"), default="preview")
    wait = subparsers.add_parser("wait")
    wait.add_argument("project_dir", type=Path)
    wait.add_argument("--quality", choices=("preview", "final"), default="preview")
    wait.add_argument("--timeout", type=float, default=55.0)
    args = parser.parse_args()

    if args.action == "start":
        return start_job(args.project_dir, args.quality, args.no_subtitles, args.force)
    if args.action == "_worker":
        return run_worker(args.project_dir, args.quality, args.no_subtitles, args.force)
    if args.action == "status":
        print_state(current_state(args.project_dir.resolve(), args.quality))
        return 0
    print_state(wait_for_job(args.project_dir.resolve(), args.quality, args.timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
