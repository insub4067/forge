import asyncio
import shlex

from ..config import settings


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
        return stdout.decode(errors="replace")

    async def _run_host(self, command: str, timeout: int) -> str:
        """호스트에서 직접 실행. 에이전트가 학습한 /workspace 경로를 실제 워크스페이스로 치환.
        ponytail: 문자열 치환은 단순하지만 에이전트가 /workspace를 일관되게 쓰므로 충분."""
        real_cmd = command.replace("/workspace", self.workspace)
        proc = await asyncio.create_subprocess_shell(
            real_cmd,
            cwd=self.workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"(타임아웃 {timeout}초 초과, 강제 종료)"
        return stdout.decode(errors="replace")
