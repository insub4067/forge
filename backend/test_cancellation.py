"""실행 중 취소 시 subprocess까지 죽는지 검증(신뢰성 불변식).

취소는 스텝 경계 플래그로만 폴링돼 실행 중인 긴 bash를 못 멈추던 구멍이 있었다.
executor가 CancelledError에서 프로세스 그룹을 죽이므로, 취소하면 명령이 백그라운드로
계속 돌지 않는다. 실행:
    cd backend && .venv/bin/python -m pytest -q test_cancellation.py
"""
import asyncio

from app.sandbox.executor import DockerSandbox


async def test_host_subprocess_killed_on_cancel(tmp_path):
    # sleep 후 marker 생성하는 명령을 실행 중 취소 → marker가 생기면 안 됨(= 죽었어야).
    marker = tmp_path / "done.marker"
    sb = DockerSandbox(workspace=str(tmp_path))
    task = asyncio.ensure_future(sb._run_host(f"sleep 1.5 && touch {marker}", 30))
    await asyncio.sleep(0.4)  # 명령이 실제로 시작할 시간
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(2.0)  # 안 죽었다면 이 사이에 sleep이 끝나 marker를 만든다
    assert not marker.exists(), "취소됐는데 subprocess가 살아남아 marker를 생성했다"


async def test_host_normal_completion_still_works(tmp_path):
    # 취소가 없으면 정상 완료 결과를 그대로 돌려줘야 한다(회귀 방지).
    sb = DockerSandbox(workspace=str(tmp_path))
    out = await sb._run_host("echo forge-ok", 30)
    assert "forge-ok" in out
