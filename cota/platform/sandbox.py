"""Session-scoped sandbox for isolated bot execution.

Each sandbox provides a full cota runtime in an isolated environment.
Lifecycle is per-session: created on first request, reused across turns,
destroyed after idle timeout.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SandboxConfig:
    image: str = 'cota-bot'
    idle_timeout: int = 3600
    memory_mb: int = 512
    cpu: float = 1.0


class Sandbox(ABC):
    """Isolated execution environment for a single bot session."""

    @abstractmethod
    async def create(self, config: SandboxConfig) -> None:
        """Start the sandbox. Idempotent if already running."""

    @abstractmethod
    async def exec(self, command: str, *, timeout: float = 60) -> str:
        """Run a command inside the sandbox and return its stdout."""

    @abstractmethod
    async def put_file(self, path: str, content: bytes) -> None:
        """Write a file into the sandbox filesystem."""

    @abstractmethod
    async def get_file(self, path: str) -> bytes:
        """Read a file from the sandbox filesystem."""

    @abstractmethod
    async def destroy(self) -> None:
        """Stop and remove the sandbox. Safe to call if already destroyed."""

    @abstractmethod
    async def is_alive(self) -> bool:
        """Check if the sandbox is running."""


class DockerSandbox(Sandbox):
    """Default sandbox using Docker containers.

    Requires the Docker daemon and the ``docker`` CLI on the host.
    Startup time ~1s, suitable for per-session lifecycle.
    """

    def __init__(self, name: str):
        self.name = name
        self._container_id: str | None = None

    async def create(self, config: SandboxConfig) -> None:
        if self._container_id and await self.is_alive():
            return
        cmd = [
            'docker', 'run', '-d',
            '--name', self.name,
            '--memory', f'{config.memory_mb}m',
            '--cpus', str(config.cpu),
            '--stop-timeout', str(config.idle_timeout),
            config.image,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f'Failed to create container: {stderr.decode().strip()}')
        self._container_id = stdout.decode().strip()[:12]
        logger.info('Created Docker sandbox %s (%s)', self.name, self._container_id)

    async def exec(self, command: str, *, timeout: float = 60) -> str:
        if not self._container_id:
            raise RuntimeError('Sandbox not created')
        proc = await asyncio.create_subprocess_exec(
            'docker', 'exec', self._container_id, 'sh', '-c', command,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(f'Command failed (exit {proc.returncode}): {stderr.decode().strip()}')
        return stdout.decode()

    async def put_file(self, path: str, content: bytes) -> None:
        if not self._container_id:
            raise RuntimeError('Sandbox not created')
        proc = await asyncio.create_subprocess_exec(
            'docker', 'exec', '-i', self._container_id, 'sh', '-c', f'cat > {path}',
            stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate(input=content)
        if proc.returncode != 0:
            raise RuntimeError(f'Failed to write file: {stderr.decode().strip()}')

    async def get_file(self, path: str) -> bytes:
        if not self._container_id:
            raise RuntimeError('Sandbox not created')
        proc = await asyncio.create_subprocess_exec(
            'docker', 'exec', self._container_id, 'cat', path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f'Failed to read file: {stderr.decode().strip()}')
        return stdout

    async def destroy(self) -> None:
        if not self._container_id:
            return
        proc = await asyncio.create_subprocess_exec(
            'docker', 'rm', '-f', self._container_id,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        logger.info('Destroyed Docker sandbox %s', self.name)
        self._container_id = None

    async def is_alive(self) -> bool:
        if not self._container_id:
            return False
        proc = await asyncio.create_subprocess_exec(
            'docker', 'inspect', '-f', '{{.State.Running}}', self._container_id,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() == 'true'


class GVisorSandbox(DockerSandbox):
    """Enhanced-isolation sandbox using Docker with gVisor (runsc) runtime.

    Same interface as DockerSandbox but runs containers under gVisor's
    user-space kernel for stronger isolation. No KVM required.
    Install: https://gvisor.dev/docs/user_guide/install/
    """

    async def create(self, config: SandboxConfig) -> None:
        if self._container_id and await self.is_alive():
            return
        cmd = [
            'docker', 'run', '-d',
            '--runtime=runsc',
            '--name', self.name,
            '--memory', f'{config.memory_mb}m',
            '--cpus', str(config.cpu),
            '--stop-timeout', str(config.idle_timeout),
            config.image,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f'Failed to create gVisor sandbox: {stderr.decode().strip()}')
        self._container_id = stdout.decode().strip()[:12]
        logger.info('Created gVisor sandbox %s (%s)', self.name, self._container_id)


def create_sandbox(name: str, *, runtime: str = 'docker') -> Sandbox:
    """Factory for sandbox instances.

    Args:
        name: Unique sandbox name (typically session_id).
        runtime: 'docker' (default) or 'gvisor'.
    """
    if runtime == 'gvisor':
        return GVisorSandbox(name)
    if runtime == 'docker':
        return DockerSandbox(name)
    raise ValueError(f'Unknown sandbox runtime: {runtime}; use docker or gvisor')
