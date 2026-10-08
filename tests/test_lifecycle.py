import ast
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from astrbot_plugin_mahjongsoul.network.host_prober import HostProber
from astrbot_plugin_mahjongsoul.paifuya.data import api as native
from astrbot_plugin_mahjongsoul.paifuya.data.models.player_num import PlayerNum




@pytest.mark.asyncio
async def test_prober_selects_best_reachable_mirror(monkeypatch):
    async def ping(host):
        loss, rtt = {'a': (0, 20), 'b': (0, 5), 'c': (1, 0)}[host]
        return SimpleNamespace(packet_loss=loss, avg_rtt=rtt)
    monkeypatch.setattr('astrbot_plugin_mahjongsoul.network.host_prober.async_ping', ping)
    prober = HostProber(['a', 'b', 'c'])
    assert await prober.select_host()
    assert prober.host == 'b'


@pytest.mark.asyncio
async def test_prober_close_cancels_child_pings_and_can_restart(monkeypatch):
    started = asyncio.Event()
    cancelled = []
    async def ping(host):
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.append(host)
    monkeypatch.setattr('astrbot_plugin_mahjongsoul.network.host_prober.async_ping', ping)
    prober = HostProber(['a', 'b'])
    await prober.close()  # also safe before startup
    await prober.start()
    task = prober._select_host_daemon_task
    await prober.start()
    assert prober._select_host_daemon_task is task
    await asyncio.wait_for(started.wait(), timeout=2)
    await prober.close()
    assert task.done() and set(cancelled) == {'a', 'b'}
    await prober.start()
    assert prober._select_host_daemon_task is not task
    await prober.close()


@pytest.mark.asyncio
async def test_native_lifecycle_starts_and_stops_prober(context, monkeypatch):
    from astrbot_plugin_mahjongsoul.main import Majsoul
    start, close = AsyncMock(), AsyncMock()
    monkeypatch.setattr(native.prober, 'start', start)
    monkeypatch.setattr(native.prober, 'close', close)
    plugin = Majsoul(context, {})
    await plugin.initialize()
    await plugin.terminate()
    start.assert_awaited_once()
    close.assert_awaited_once()


@pytest.mark.parametrize('existing', [None, {}, {'test:101': 'current-player'}])
async def test_binding_directory_upgrade_preserves_data(context, monkeypatch, tmp_path, existing):
    from astrbot_plugin_mahjongsoul.main import Majsoul
    legacy = tmp_path / 'astrbot_plugin_majsoul' / 'bindings.json'
    legacy.parent.mkdir()
    old_bindings = {'test:101': 'legacy-player'}
    legacy.write_text(json.dumps(old_bindings), encoding='utf-8')
    current = tmp_path / 'astrbot_plugin_mahjongsoul' / 'bindings.json'
    if existing is not None:
        current.parent.mkdir()
        current.write_text(json.dumps(existing), encoding='utf-8')
    monkeypatch.setattr(native.prober, 'start', AsyncMock())
    monkeypatch.setattr(native.prober, 'close', AsyncMock())
    plugin = Majsoul(context, {})
    await plugin.initialize()
    try:
        expected = old_bindings if existing is None else existing
        assert plugin.bindings.path == current
        assert plugin.bindings.data == expected
        assert json.loads(current.read_text('utf-8')) == expected
        assert json.loads(legacy.read_text('utf-8')) == old_bindings
    finally:
        await plugin.terminate()
