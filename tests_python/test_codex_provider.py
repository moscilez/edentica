import asyncio
import json
from pathlib import Path
import pytest

from backend.codex_provider import CodexProvider, cli_environment, command
from backend.programs import Programs


def test_local_provider_cannot_be_enabled_in_hackathon(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("EDENTICA_MODE", "hackathon")
    with pytest.raises(ValueError, match="local"):
        Programs(None, None)


def test_cli_command_and_environment_are_restricted(monkeypatch, tmp_path):
    args = command("codex.exe", tmp_path)
    assert "--ignore-user-config" in args and "--ephemeral" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    for feature in ("shell_tool", "apps", "plugins", "multi_agent", "browser_use"):
        assert args[args.index(feature) - 1] == "--disable"
    assert "--dangerously-bypass-approvals-and-sandbox" not in args
    monkeypatch.setenv("DATABASE_URL", "private-database")
    monkeypatch.setenv("OPENAI_API_KEY", "not-to-be-used")
    monkeypatch.setenv("CLOUDRU_API_KEY", "private-key")
    env = cli_environment()
    assert not any(key in env for key in ("DATABASE_URL", "OPENAI_API_KEY", "CLOUDRU_API_KEY"))


def test_local_provider_rejects_public_bind(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("EDENTICA_MODE", "local")
    monkeypatch.setenv("HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        Programs(None, None)


class Input:
    def write(self, payload):
        self.payload = payload

    async def drain(self):
        pass

    def close(self):
        pass


class FakeProcess:
    def __init__(self, events):
        self.stdin = Input()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(b"\n".join(json.dumps(event).encode() for event in events) + b"\n")
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = 0

    async def wait(self):
        return self.returncode


def test_cli_reads_json_and_usage_without_real_requests(monkeypatch):
    async def run():
        async def spawn(*args, **kwargs):
            return FakeProcess([
                {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}},
                {"type": "turn.completed", "usage": {"input_tokens": 30, "output_tokens": 10}},
            ])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        client = CodexProvider()
        client.path = "codex.exe"
        client.authenticated = True
        result = await client.complete("Инструкция", {"request": "Пример"})
        assert result["value"] == {"ok": True}
        assert result["usage"] == {"inputTokens": 30, "outputTokens": 10}
    asyncio.run(run())


def test_cli_rejects_tool_events(monkeypatch):
    async def run():
        async def spawn(*args, **kwargs):
            return FakeProcess([{"type": "item.started", "item": {"type": "command_execution"}}])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        client = CodexProvider()
        client.path = "codex.exe"
        client.authenticated = True
        with pytest.raises(ValueError, match="инструмент"):
            await client.complete("Инструкция", {})
    asyncio.run(run())
