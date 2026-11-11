"""Sandbox factory and contract tests (no Docker daemon required)."""
import pytest

from cota.platform.sandbox import (
    Sandbox, DockerSandbox, GVisorSandbox, SandboxConfig, create_sandbox,
)


def test_create_sandbox_docker():
    sb = create_sandbox('test-session')
    assert isinstance(sb, DockerSandbox)
    assert sb.name == 'test-session'


def test_create_sandbox_gvisor():
    sb = create_sandbox('test-session', runtime='gvisor')
    assert isinstance(sb, GVisorSandbox)
    assert isinstance(sb, DockerSandbox)


def test_create_sandbox_unknown_runtime():
    with pytest.raises(ValueError, match='Unknown sandbox runtime'):
        create_sandbox('s', runtime='firecracker')


def test_sandbox_config_defaults():
    config = SandboxConfig()
    assert config.image == 'cota-bot'
    assert config.idle_timeout == 3600
    assert config.memory_mb == 512
    assert config.cpu == 1.0


def test_sandbox_config_custom():
    config = SandboxConfig(image='my-bot:v2', memory_mb=1024, cpu=2.0, idle_timeout=7200)
    assert config.image == 'my-bot:v2'
    assert config.memory_mb == 1024


def test_sandbox_is_abstract():
    assert issubclass(Sandbox, type) is False
    with pytest.raises(TypeError):
        Sandbox()


@pytest.mark.asyncio
async def test_docker_sandbox_not_alive_before_create():
    sb = DockerSandbox('uncreated')
    assert not await sb.is_alive()


@pytest.mark.asyncio
async def test_docker_sandbox_exec_before_create():
    sb = DockerSandbox('uncreated')
    with pytest.raises(RuntimeError, match='not created'):
        await sb.exec('echo hello')


@pytest.mark.asyncio
async def test_docker_sandbox_destroy_before_create():
    sb = DockerSandbox('uncreated')
    await sb.destroy()
