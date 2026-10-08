import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from Astrbot_plugin_mahjongsoul.network.host_prober import HostProber
from Astrbot_plugin_mahjongsoul.paifuya.data import api as native
from Astrbot_plugin_mahjongsoul.paifuya.data.models.player_num import PlayerNum




@pytest.mark.asyncio
async def test_prober_selects_best_reachable_mirror(monkeypatch):
    async def ping(host):
        loss, rtt = {'a': (0, 20), 'b': (0, 5), 'c': (1, 0)}[host]
        return SimpleNamespace(packet_loss=loss, avg_rtt=rtt)
    monkeypatch.setattr('Astrbot_plugin_mahjongsoul.network.host_prober.async_ping', ping)
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
    monkeypatch.setattr('Astrbot_plugin_mahjongsoul.network.host_prober.async_ping', ping)
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
    from Astrbot_plugin_mahjongsoul.main import Majsoul
    start, close = AsyncMock(), AsyncMock()
    monkeypatch.setattr(native.prober, 'start', start)
    monkeypatch.setattr(native.prober, 'close', close)
    plugin = Majsoul(context, {})
    await plugin.initialize()
    await plugin.terminate()
    start.assert_awaited_once()
    close.assert_awaited_once()
