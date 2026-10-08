from astrbot.api.message_components import Plain as Text, Image as AstrImage
from astrbot.api import logger
from ..errors import QueryError, BadRequestError, PaifuyaRateLimitError
from asyncio import to_thread as run_in_my_executor

def Image(value):
    return AstrImage.fromBytes(value)

from asyncio import create_task, wait_for
from datetime import datetime, timezone
from io import StringIO
from typing import AbstractSet, Optional
from httpx import HTTPError, HTTPStatusError
from .ai_comment import generate_ai_comment
from .data.api import paifuya_api as api
from .data.models.player_num import PlayerNum
from .data.models.room_rank import all_four_player_room_rank, all_three_player_room_rank, RoomRank
from .mappers.player_extended_stats import map_player_extended_stats
from .mappers.player_stats import map_player_stats
from .mappers.room_rank import map_room_rank
from ..config import conf
_PLAYER_RECORDS_PAGE_SIZE = 500

async def _try_authorized_records_start_time(player_num: PlayerNum, player_id: int, start_time: datetime, end_time: datetime, room_rank: AbstractSet[RoomRank], limit: int) -> Optional[datetime]:
    api_key = conf.majsoul_paifuya_api_key.strip()
    if not api_key:
        return None
    found = 0
    oldest_time = start_time
    try:
        async for record in api[player_num].player_records_stream(player_id, start_time, end_time, room_rank, batch=min(limit, _PLAYER_RECORDS_PAGE_SIZE), descending=True, api_key=api_key):
            found += 1
            oldest_time = record.start_time
            if found >= limit:
                break
    except (HTTPError, PaifuyaRateLimitError) as e:
        logger.warning('Paifuya authorized info request failed (%s); no anonymous fallback', type(e).__name__)
        raise
    return oldest_time

async def handle_majsoul_info(emit, nickname: str, player_num: PlayerNum, *, room_rank: Optional[AbstractSet[RoomRank]]=None, start_time: Optional[datetime]=None, end_time: Optional[datetime]=None, limit: Optional[int]=None):
    default_start_time = start_time is None
    default_end_time = end_time is None
    if room_rank is None:
        if player_num == PlayerNum.four:
            room_rank = all_four_player_room_rank
        elif player_num == PlayerNum.three:
            room_rank = all_three_player_room_rank
    if start_time is None:
        start_time = datetime.fromisoformat('2010-01-01T00:00:00').astimezone(timezone.utc)
    if end_time is None:
        end_time = datetime.now(timezone.utc)
    players = await api[player_num].search_player(nickname)
    if not players:
        raise QueryError('没有查询到该角色在金之间以上的对局数据呢~')
    room_rank_text = map_room_rank(room_rank)
    for idx, p in enumerate(players):
        sio = StringIO()
        sio.write(f'====== 昵称：{p.nickname} ======\n')
        try:
            stats_loaded_by_fallback = False
            if limit is not None:
                start_time_used = await _try_authorized_records_start_time(player_num, p.id, start_time, end_time, room_rank, limit)
                if start_time_used is None:
                    latest_timestamp = p.latest_timestamp
                    if latest_timestamp > 10000000000:
                        latest_timestamp /= 1000
                    latest_time = datetime.fromtimestamp(latest_timestamp, tz=timezone.utc)
                    try:
                        start_time_used, player_stats = await api[player_num].player_stats_for_recent_games(p.id, start_time, end_time, room_rank, limit=limit, latest_time=latest_time)
                    except RuntimeError as e:
                        raise QueryError(f'无法精确定位最近{limit}场，请改用时间范围查询') from e
                    stats_loaded_by_fallback = True
            else:
                start_time_used = start_time
            if stats_loaded_by_fallback:
                if player_stats is None:
                    player_extended_stats = None
                else:
                    player_extended_stats = await api[player_num].player_extended_stats(p.id, start_time_used, end_time, room_rank)
            else:
                stats_task = create_task(api[player_num].player_stats(p.id, start_time_used, end_time, room_rank))
                ext_task = create_task(api[player_num].player_extended_stats(p.id, start_time_used, end_time, room_rank))
                player_stats = await stats_task
                player_extended_stats = await ext_task
        except HTTPStatusError as e:
            if e.response.status_code == 404:
                sio.write('没有该账号的对局数据')
                await emit([Text(sio.getvalue().strip())])
                continue
            else:
                raise e
        if player_stats is None:
            sio.write(f'没有查询到{room_rank_text}的对局数据呢~')
            await emit([Text(sio.getvalue().strip())])
            continue
        single_sio = StringIO()
        map_player_stats(single_sio, player_stats, room_rank_text, player_num)
        single_sio.write('\n')
        map_player_extended_stats(single_sio, player_extended_stats, room_rank_text)
        stats_text = single_sio.getvalue().strip()
        sio.write(stats_text)
        if conf.majsoul_send_link:
            sio.write('\n\n更多信息：\n')
            if player_num == PlayerNum.four:
                url = f'https://amae-koromo.sapk.ch/player/{p.id}/'
            else:
                url = f'https://ikeda.sapk.ch/player/{p.id}/'
            url += '.'.join(map(lambda x: str(x.value), room_rank))
            if not default_start_time:
                url += '/' + start_time.strftime('%Y-%m-%d')
            if not default_end_time:
                url += '/' + end_time.strftime('%Y-%m-%d')
            sio.write(url)
        msg = sio.getvalue().strip()
        await emit([Text(msg)])
        try:
            ai_comment = await generate_ai_comment(stats_text)
            if ai_comment:
                await emit([Text(f'AI锐评：\n{ai_comment.strip()}')])
        except Exception as e:
            await emit([Text(f'AI锐评生成失败：{e}')])
