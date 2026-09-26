"""CLI диагностики: launch detached-супервизора / run (точка входа)."""

import os
import subprocess
import sys
from datetime import datetime
from typing import Optional

from lib import diagnose as _dg
from lib.diagnose import MSG_BUSY, acquire_lock, release_lock
from lib.diagnostics.diagnose_supervisor import DiagnoseSupervisor


def launch_detached(text: str,
                    repo_root: Optional[str] = None) -> int:
    """Спавнит detached-процесс супервизора, мгновенно возвращается."""
    repo_root = repo_root or _dg.REPO_ROOT
    logs_dir = os.path.join(repo_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = os.path.join(logs_dir, f"diagnose_{stamp}.log")
    cmd = [sys.executable, "-m", "lib.diagnose", "run", text]
    kwargs: dict = {
        "cwd": repo_root,
        "stdin": subprocess.DEVNULL,
        "stdout": open(log_path, "ab"),
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
    return 0


def main(argv: Optional[list] = None) -> int:
    """CLI: `python -m lib.diagnose launch [текст]` / `run [текст]`.

    launch — спавн detached-супервизора (для шаблона commands.json,
    мгновенный возврат). run — сам супервизор (не вызывать вручную).
    """
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in ("launch", "run"):
        print("usage: python -m lib.diagnose launch [текст] | run [текст]")
        return 2
    text = " ".join(args[1:]).strip()
    if args[0] == "launch":
        try:
            return launch_detached(text)
        except Exception as e:
            print(f"error: {e}")
            return 1
    if not acquire_lock():
        sup = DiagnoseSupervisor()
        sup._say(MSG_BUSY)
        return 4
    try:
        return DiagnoseSupervisor().supervise(text)
    finally:
        release_lock()
