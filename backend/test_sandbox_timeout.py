"""bash 타임아웃이 자식 프로세스까지 종료하는지 검증(orphan 방지).

이전엔 proc.kill()이 셸만 죽여 `find /` 같은 자식이 orphan으로 남아 디스크를 계속 스캔했다.
프로세스 그룹째 종료해 자식까지 확실히 죽인다.
실행: python test_sandbox_timeout.py
"""
import asyncio
import subprocess

from app.sandbox.executor import DockerSandbox


async def main():
    sb = DockerSandbox(workspace="/tmp")
    # 자식(sleep 30)을 spawn하고 wait — 2초 타임아웃으로 강제 종료
    out = await sb._run_host("sleep 30 & wait", timeout=2)
    assert "타임아웃" in out, out
    await asyncio.sleep(0.5)
    r = subprocess.run(["pgrep", "-f", "sleep 30"], capture_output=True, text=True)
    assert not r.stdout.strip(), f"orphan 프로세스가 남음: {r.stdout!r}"
    print("bash 타임아웃 orphan-kill: OK — 자식까지 종료(orphan 없음)")
    print("\n통과 ✓")


if __name__ == "__main__":
    asyncio.run(main())
