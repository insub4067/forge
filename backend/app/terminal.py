"""Host PTY terminal — 사용자가 Agent와 같은 실행 환경(맥)에 직접 붙는 인터랙티브 셸.

os.openpty로 PTY를 열고 셸을 붙인 뒤, WebSocket으로 stdin/stdout을 중계한다.
단일 사용자 개인 맥(host 모드) 전제. 프로토콜(client→server, JSON text):
  {"type":"input","data":"ls\n"}
  {"type":"resize","cols":100,"rows":30}
server→client는 터미널 출력 텍스트(raw)를 그대로 보낸다.
"""
import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios
from pathlib import Path


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def _spawn(workspace: str, cols: int, rows: int):
    """PTY를 열고 로그인 셸을 붙여 (pid, master_fd)를 돌려준다."""
    import subprocess

    master, slave = pty.openpty()
    _set_winsize(master, rows, cols)
    shell = os.environ.get("SHELL", "/bin/zsh")
    cwd = workspace if workspace and Path(workspace).is_dir() else str(Path.home())
    proc = subprocess.Popen(
        [shell, "-l"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=cwd,
        start_new_session=True,  # 자체 세션/프로세스 그룹 → 정리 시 그룹째 종료
        env={**os.environ, "TERM": "xterm-256color"},
    )
    os.close(slave)
    os.set_blocking(master, False)
    return proc, master


async def bridge(ws, workspace: str, cols: int = 80, rows: int = 24) -> None:
    """WebSocket ↔ PTY 중계. ws는 이미 accept된 상태로 들어온다."""
    import json

    proc, master = _spawn(workspace, cols, rows)
    loop = asyncio.get_event_loop()
    out_q: asyncio.Queue = asyncio.Queue()

    def _on_readable():
        try:
            data = os.read(master, 8192)
        except OSError:
            data = b""
        if data:
            out_q.put_nowait(data)
        else:
            loop.remove_reader(master)
            out_q.put_nowait(None)  # EOF

    loop.add_reader(master, _on_readable)

    async def _pump_out():
        while True:
            data = await out_q.get()
            if data is None:
                break
            try:
                await ws.send_text(data.decode("utf-8", errors="replace"))
            except Exception:
                break

    out_task = asyncio.create_task(_pump_out())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            t = msg.get("type")
            if t == "input":
                try:
                    os.write(master, msg.get("data", "").encode("utf-8"))
                except OSError:
                    break
            elif t == "resize":
                _set_winsize(master, int(msg.get("rows", rows)), int(msg.get("cols", cols)))
    except Exception:
        pass  # WebSocket 종료(disconnect 등)
    finally:
        try:
            loop.remove_reader(master)
        except Exception:
            pass
        out_task.cancel()
        # 셸 프로세스 그룹째 종료
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            os.close(master)
        except Exception:
            pass
