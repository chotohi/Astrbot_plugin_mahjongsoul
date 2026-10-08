"""Small native AstrBot utilities, vendored into each independent plugin."""
import asyncio
import json
import os
import tempfile
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Star, StarTools
from astrbot.api.message_components import Plain, Image


def settings(config):
    """Allow complex original configuration through a validated JSON object."""
    result = dict(config or {})
    advanced = result.pop('advanced', '{}')
    if isinstance(advanced, str):
        advanced = json.loads(advanced or '{}')
    if not isinstance(advanced, dict):
        raise ValueError('advanced 必须为 JSON 对象')
    result.update(advanced)
    return result


def data_dir(name):
    return Path(StarTools.get_data_dir(name))


class JsonStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.path.read_text('utf-8')) if self.path.exists() else {}

    def save(self):
        fd, name = tempfile.mkstemp(dir=self.path.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)


class NativePlugin:
    def __init__(self, context, config=None):
        super().__init__(context)
        self.config = config or {}
        self.options = settings(config)
        self.tasks = set()

    def background(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        def done(t):
            self.tasks.discard(t)
            if not t.cancelled() and t.exception():
                logger.error(f'{type(self).__name__} 后台任务失败: {t.exception()}')
        task.add_done_callback(done)
        return task

    async def terminate(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()


def arguments(event):
    parts = event.message_str.strip().split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ''


def session_user(event):
    return f'{event.unified_msg_origin}:{event.get_sender_id()}'


def group_admin(event):
    if event.is_admin():
        return True
    raw = getattr(event.message_obj, 'raw_message', {}) or {}
    if not isinstance(raw, dict):
        return False
    return bool(event.get_group_id()) and raw.get('sender', {}).get('role') in ('owner', 'admin')


async def action(event, name, **params):
    bot = getattr(event, 'bot', None)
    if bot is None or not hasattr(bot, 'call_action'):
        raise ValueError('该操作需要 AstrBot 的 OneBot V11 适配器')
    sid = getattr(event.message_obj, 'self_id', '')
    if sid:
        params['self_id'] = str(sid)
    return await bot.call_action(name, **params)


def image_component(value):
    if isinstance(value, bytes):
        return Image.fromBytes(value)
    value = str(value)
    return Image.fromURL(value) if value.startswith(('http://', 'https://')) else Image.fromFileSystem(value)


async def send(event, content):
    result = event.plain_result(content) if isinstance(content, str) else event.chain_result(content)
    return await event.send(result)


async def send_chains(event, chains, forward=False):
    from astrbot.api.message_components import Node, Nodes
    chains = [list(chain) for chain in chains if chain]
    if forward and len(chains) > 1 and event.get_platform_name() == 'aiocqhttp':
        nodes = [Node(uin=str(event.message_obj.self_id), name='AstrBot', content=chain) for chain in chains]
        await event.send(event.chain_result([Nodes(nodes)]))
    else:
        for chain in chains:
            await event.send(event.chain_result(chain))
