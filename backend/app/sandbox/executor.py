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
