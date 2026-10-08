import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from astrbot_plugin_mahjongsoul.config import Config, DEFAULT_AI_PROMPT, conf
from astrbot_plugin_mahjongsoul.errors import PaifuyaRateLimitError
from astrbot_plugin_mahjongsoul.paifuya import ai_comment, query_majsoul_pt_plot as plot
from astrbot_plugin_mahjongsoul.paifuya.data.models.player_num import PlayerNum
from astrbot_plugin_mahjongsoul.paifuya.data.models.player_info import PlayerLevel


def test_schema_defaults_and_limit_validation():
    schema = json.loads((Path(__file__).resolve().parents[1] / '_conf_schema.json').read_text('utf-8'))
    assert Config().majsoul_pt_max_games == schema['majsoul_pt_max_games']['default'] == 2000
    assert Config().majsoul_ai_prompt == schema['majsoul_ai_prompt']['default'] == DEFAULT_AI_PROMPT
    assert '你是一个雀魂猫娘。' in DEFAULT_AI_PROMPT
    assert '- 要给出问题的解决方案' in DEFAULT_AI_PROMPT
    for value in (0, -1):
        with pytest.raises(ValidationError):
            Config(majsoul_pt_max_games=value)


@pytest.mark.parametrize('available,limit,expected_calls', [(2500, 2000, 4), (740, 2000, 2), (1500, 1200, 3), (100, 30, 1)])
async def test_authenticated_pt_pagination(monkeypatch, available, limit, expected_calls):
    monkeypatch.setattr(conf, 'majsoul_paifuya_api_key', ' Bearer dummy-paifuya-key ')
    end = datetime(2026, 10, 8, tzinfo=timezone.utc)
    source = [SimpleNamespace(start_time=end - timedelta(minutes=i), id=i) for i in range(available)]
    async def fetch(player_id, start_time, cursor, rooms, **kwargs):
        assert kwargs['api_key'] == 'dummy-paifuya-key'
        assert kwargs['descending'] is True and kwargs['limit'] <= 500
        return [r for r in source if start_time <= r.start_time <= cursor][:kwargs['limit']]
    fetch_mock = AsyncMock(side_effect=fetch)
    monkeypatch.setitem(plot.api, PlayerNum.three, SimpleNamespace(player_records=fetch_mock))
    records = await plot._try_authorized_pt_records(PlayerNum.three, 123, end - timedelta(days=7), end, set(), limit)
    assert [r.id for r in records] == list(range(min(available, limit)))
    assert fetch_mock.await_count == expected_calls


@pytest.mark.parametrize('rate_limited', [False, True])
async def test_pt_later_page_failure(monkeypatch, rate_limited):
    monkeypatch.setattr(conf, 'majsoul_paifuya_api_key', 'dummy-key')
    end = datetime(2026, 10, 8, tzinfo=timezone.utc)
    page = [SimpleNamespace(start_time=end - timedelta(minutes=i)) for i in range(500)]
    error = (PaifuyaRateLimitError(auth_sent=True) if rate_limited else
             httpx.HTTPStatusError('not found', request=httpx.Request('GET', 'https://example.com'),
                                   response=httpx.Response(404)))
    fetch = AsyncMock(side_effect=[page, error])
    monkeypatch.setitem(plot.api, PlayerNum.three, SimpleNamespace(player_records=fetch))
    args = (PlayerNum.three, 123, end - timedelta(days=7), end, set(), 2000)
    if rate_limited:
        with pytest.raises(PaifuyaRateLimitError):
            await plot._try_authorized_pt_records(*args)
    else:
        assert await plot._try_authorized_pt_records(*args) == page
    assert fetch.await_count == 2


@pytest.mark.parametrize('cap,requested,expected', [(2000, None, 2000), (3000, 2500, 2500), (800, 2000, 800)])
async def test_plot_uses_configured_cap_and_chronological_order(monkeypatch, cap, requested, expected):
    monkeypatch.setattr(conf, 'majsoul_paifuya_api_key', 'dummy-key')
    monkeypatch.setattr(conf, 'majsoul_pt_max_games', cap)
    player = SimpleNamespace(id=123, nickname='example')
    rank = PlayerLevel(id=10301, score=600, delta=0).id
    records = [SimpleNamespace(id=i, players=[SimpleNamespace(id=123, rank=rank)]) for i in range(expected)]
    fetch = AsyncMock(return_value=records)
    monkeypatch.setattr(plot, '_try_authorized_pt_records', fetch)
    monkeypatch.setitem(plot.api, PlayerNum.three, SimpleNamespace(search_player=AsyncMock(return_value=[player])))
    draw = Mock(side_effect=lambda stream, *args: stream.write(b'fake-png'))
    monkeypatch.setattr(plot, 'draw', draw)
    emit = AsyncMock()
    await plot.handle_majsoul_pt_plot(emit, 'example', PlayerNum.three, limit=requested)
    assert fetch.await_args.args[-1] == expected
    assert [r.id for r in draw.call_args.args[-1]] == list(reversed(range(expected)))
    emit.assert_awaited_once()


@pytest.mark.parametrize('prompt', [DEFAULT_AI_PROMPT, '你是一位教练。\n请简洁点评。'])
async def test_ai_sends_configured_system_prompt(monkeypatch, prompt):
    monkeypatch.setattr(conf, 'majsoul_ai_api_key', 'dummy-ai-key')
    monkeypatch.setattr(conf, 'majsoul_ai_prompt', prompt)
    create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='comment'))]))
    manager = AsyncMock()
    manager.__aenter__.return_value = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(ai_comment, 'AsyncOpenAI', Mock(return_value=manager))
    await ai_comment.generate_ai_comment('player statistics')
    assert create.await_args.kwargs['messages'] == [
        {'role': 'system', 'content': prompt.strip()},
        {'role': 'user', 'content': 'player statistics'},
    ]
