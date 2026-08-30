"""run_verify가 bash 도구와 동일하게 BLOCKED_COMMANDS를 거부하는지 검증한다(P0-1 보강).

gate의 verification_method는 모델이 작성하므로, bash 도구가 거부하는 자기종료/권한상승
명령(pkill·sudo·uvicorn 등)이 gate 검증 경로로 새어 실행되면 안 된다. 차단은 sandbox_mode
분기 이전이라 docker/host 무관하게 동작한다(무샌드박스·무LLM).

실행: cd backend && python -m pytest test_run_verify_blocked.py -q
"""
import asyncio

from app.sandbox.executor import BLOCKED_COMMANDS, DockerSandbox


def test_run_verify_rejects_blocked_commands():
    sb = DockerSandbox(workspace="/tmp")
    for cmd in ["pkill -f uvicorn", "sudo rm x", "uvicorn app.main", "kill 1234"]:
        code, out = asyncio.run(sb.run_verify(cmd))
        assert code == 126, f"차단 안 됨: {cmd!r} → exit {code}"
        assert "차단" in out


def test_blocked_commands_single_source():
    """registry의 bash 도구와 executor.run_verify가 같은 목록을 공유한다(정책 단일화)."""
    from app.tools import registry

    assert registry.BLOCKED_COMMANDS is BLOCKED_COMMANDS
