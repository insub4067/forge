import asyncio
import re
import shlex

from ..config import settings

# 파괴적/위험 명령 차단(특히 host 모드에서 자동 승인 시 안전장치).
# 개인 Mac을 되돌릴 수 없게 망가뜨리는 패턴만 최소로 막는다.
_DANGEROUS = [
    r"\brm\s+-rf?\s+(/|~|\$HOME|\.\.)(\s|/|$)",   # rm -rf / ~ $HOME ..
    r":\(\)\s*\{",                                  # fork bomb
    r"\bmkfs\b", r"\bdd\b[^|]*\bof=/dev/",          # 디스크 포맷/덮어쓰기
    r">\s*/dev/(sd|disk|nvme)",                      # 블록 디바이스 직접 쓰기
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b",
    r"\bgit\b[^|]*\bpush\b[^|]*(-f|--force)\b.*\b(main|master)\b",  # 강제 push 보호
]


def _is_dangerous(command: str) -> bool:
    return any(re.search(p, command) for p in _DANGEROUS)


class DockerSandbox:
    def __init__(self, image: str | None = None, workspace: str | None = None):
        self.image = image or settings.sandbox_image
        self.workspace = workspace or settings.workspace

    async def run(
        self,
        command: str,
        *,
        cwd: str = "/workspace",
        timeout: int = 120,
        write: bool = False,
    ) -> str:
        if _is_dangerous(command):
            return "(차단됨: 파괴적/위험 명령으로 판단되어 실행하지 않았습니다.)"
        # 옵트인 host 모드: bash를 호스트에서 직접 실행(자기검증·풀파워). 기본은 docker.
        if settings.sandbox_mode == "host":
            return await self._run_host(command, timeout)
        mount_mode = "rw" if write else "ro"
        args = [
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", "512m",
            "--cpus", "1",
            "--pids-limit", "256",
            "--user", "1000:1000",
            "-v", f"{self.workspace}:/workspace:{mount_mode}",
            "-w", cwd,
            self.image,
            "bash", "-c", command,
        ]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"(타임아웃 {timeout}초 초과, 강제 종료)"
        except asyncio.CancelledError:
            # 사용자가 실행 중 취소 — docker run 클라이언트를 죽이면 --rm 컨테이너도 정리된다.
            proc.kill()
            try:
                await proc.communicate()
            except Exception:
                pass
            raise
        return stdout.decode(errors="replace")

    async def _run_host(self, command: str, timeout: int) -> str:
        """호스트에서 직접 실행. 에이전트가 학습한 /workspace 경로를 실제 워크스페이스로 치환.
        ponytail: 문자열 치환은 단순하지만 에이전트가 /workspace를 일관되게 쓰므로 충분."""
        import os
        import signal
        real_cmd = command.replace("/workspace", self.workspace)
        proc = await asyncio.create_subprocess_shell(
            real_cmd,
            cwd=self.workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,  # 셸+자식을 한 프로세스 그룹으로 — 타임아웃 시 그룹째 종료
        )
        def _kill_group():
            # proc.kill()은 셸만 죽여 자식(find 등)이 orphan으로 남아 디스크를 계속 스캔한다.
            # 프로세스 그룹 전체(셸+자식)를 SIGKILL로 확실히 종료한다.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            _kill_group()
            await proc.communicate()
            return f"(타임아웃 {timeout}초 초과, 강제 종료)"
        except asyncio.CancelledError:
            # 사용자가 실행 중 취소 — 그룹째 죽이지 않으면 긴 명령이 백그라운드로 계속 돈다.
            _kill_group()
            try:
                await proc.communicate()
            except Exception:
                pass
            raise
        return stdout.decode(errors="replace")

    async def run_verify(self, command: str, timeout: int = 120) -> tuple[int, str]:
        """acceptance gate 검증 명령 실행 — bash 도구와 '동일한' 안전 경계를 적용하고
        (exit_code, output)을 반환한다. gate가 host /bin/sh로 직접 나가 승인·sandbox·
        dangerous-command 정책을 우회하던 구멍(P0-1)을 막는다: _is_dangerous 차단,
        sandbox_mode 준수(docker면 컨테이너·network none·workspace 마운트, host면 그룹세션),
        timeout, 취소 시 프로세스 그룹 정리. bash보다 높은 권한을 갖지 않는다."""
        if _is_dangerous(command):
            return 126, "(차단됨: 파괴적/위험 명령으로 판단되어 실행하지 않았습니다.)"
        if settings.sandbox_mode == "host":
            return await self._run_host_checked(command, timeout)
        args = [
            "docker", "run", "--rm", "--network", "none",
            "--memory", "512m", "--cpus", "1", "--pids-limit", "256",
            "--user", "1000:1000",
            "-v", f"{self.workspace}:/workspace",   # bash(write=True)와 동일 권한 — 그 이상 아님
            "-w", "/workspace",
            self.image, "bash", "-c", command,
        ]
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return 124, f"(타임아웃 {timeout}초 초과, 강제 종료)"
        except asyncio.CancelledError:
            proc.kill()
            try:
                await proc.communicate()
            except Exception:
                pass
            raise
        return proc.returncode, stdout.decode(errors="replace")

    async def _run_host_checked(self, command: str, timeout: int) -> tuple[int, str]:
        """_run_host와 같되 (exit_code, output)을 반환한다(gate 검증용). 프로세스 그룹으로
        실행해 타임아웃·취소 시 자식까지 정리한다."""
        import os
        import signal
        real_cmd = command.replace("/workspace", self.workspace)
        proc = await asyncio.create_subprocess_shell(
            real_cmd, cwd=self.workspace,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        def _kill_group():
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            _kill_group()
            await proc.communicate()
            return 124, f"(타임아웃 {timeout}초 초과, 강제 종료)"
        except asyncio.CancelledError:
            _kill_group()
            try:
                await proc.communicate()
            except Exception:
                pass
            raise
        return proc.returncode, stdout.decode(errors="replace")
