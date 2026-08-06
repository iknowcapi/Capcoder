"""
executor.py — materializes a generation's files and actually RUNS them.

This is the reality check. No human input. No "does it look right." Just:
    bash run.sh → wait 30s → capture stdout/stderr/exit_code + port_listening.
The result is a real signal fed back to the rater and the next gen's planner.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import socket
from typing import Optional

WORKSPACE_ROOT = pathlib.Path("/workspaces")
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


def _slug(s: str, fallback: str = "gen") -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")
    return s or fallback


def materialize(chain_id: str, gen: dict) -> pathlib.Path:
    """Write the gen's files to /workspaces/{chain}/{name} and return the dir."""
    slug = _slug(gen.get("name") or f"gen-{gen.get('gen')}", f"gen-{gen.get('gen')}")
    root = WORKSPACE_ROOT / chain_id[:8] / slug
    root.mkdir(parents=True, exist_ok=True)
    for f in gen.get("files", []):
        p = root / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f["content"])
        if p.suffix == ".sh":
            p.chmod(0o755)
    return root


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


async def run_workspace(
    root: pathlib.Path, timeout: int = 30, port_to_check: int = 8000
) -> dict:
    """Execute `bash run.sh` in the workspace, capture logs, verify port opens."""
    result: dict = {
        "ran": False,
        "started": False,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "port_listening": False,
        "duration_s": 0.0,
        "root": str(root),
    }
    run_sh = root / "run.sh"
    if not run_sh.exists():
        result["stderr"] = "no run.sh in workspace"
        return result

    result["ran"] = True
    env = os.environ.copy()
    # Pin the child app to a unique port so we don't clash with the parent (8001).
    # We keep 8000 in the template; users can override via APP_PORT.
    env["APP_PORT"] = str(port_to_check)
    loop = asyncio.get_running_loop()
    start = loop.time()

    proc = await asyncio.create_subprocess_exec(
        "bash", "run.sh",
        cwd=str(root),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=os.setsid,  # new process group so we can kill children too
    )

    # Poll port up to `timeout` seconds; when it opens we call it "started".
    for _ in range(timeout * 2):
        if _port_open(port_to_check):
            result["started"] = True
            result["port_listening"] = True
            break
        if proc.returncode is not None:
            break
        await asyncio.sleep(0.5)

    # Give it a beat to emit logs, then tear the whole process group down.
    await asyncio.sleep(0.5)
    import signal as _signal
    pgid = None
    try:
        pgid = os.getpgid(proc.pid)
    except Exception:
        pass
    try:
        if pgid is not None:
            os.killpg(pgid, _signal.SIGTERM)
        else:
            proc.terminate()
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            if pgid is not None:
                try: os.killpg(pgid, _signal.SIGKILL)
                except Exception: pass
            else:
                proc.kill()
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3)
            except asyncio.TimeoutError:
                stdout, stderr = b"", b""
    except ProcessLookupError:
        stdout, stderr = b"", b""

    result["exit_code"] = proc.returncode
    result["stdout"] = (stdout or b"").decode("utf-8", errors="replace")[-4000:]
    result["stderr"] = (stderr or b"").decode("utf-8", errors="replace")[-4000:]
    result["duration_s"] = round(loop.time() - start, 2)
    return result


def brief(exec_result: dict) -> str:
    """Compact one-block summary for feeding into subsequent LLM stages."""
    if not exec_result.get("ran"):
        return "EXEC: skipped (no run.sh)"
    lines = [
        f"EXEC: ran={exec_result['ran']} started={exec_result['started']} "
        f"port_listening={exec_result['port_listening']} "
        f"exit={exec_result['exit_code']} duration={exec_result['duration_s']}s",
    ]
    if exec_result.get("stderr"):
        lines.append("STDERR tail:\n" + exec_result["stderr"][-800:])
    if exec_result.get("stdout"):
        lines.append("STDOUT tail:\n" + exec_result["stdout"][-500:])
    return "\n".join(lines)
