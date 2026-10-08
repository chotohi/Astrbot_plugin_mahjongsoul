from astrbot.api.message_components import Plain as Text, Image as AstrImage
from astrbot.api import logger
from ..errors import QueryError, BadRequestError, PaifuyaRateLimitError, PT_KEY_REQUIRED
from asyncio import to_thread as run_in_my_executor

def Image(value):
    return AstrImage.fromBytes(value)

import sys
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import AbstractSet, Sequence, Optional
from httpx import HTTPError, HTTPStatusError
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.text import Text as PlotText
from .data.api import paifuya_api as api
from .data.models.game_record import GameRecord
from .data.models.player_info import PlayerInfo, PlayerLevel
from .data.models.player_num import PlayerNum
from .data.models.player_rank import PlayerMajorRank
from .data.models.room_rank import all_four_player_room_rank, all_three_player_room_rank, RoomRank
from .mappers.player_num import map_player_num
from .mappers.player_rank import map_player_rank
from ..config import conf, normalize_api_key
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib import font_manager
PLAYER_RECORDS_BATCH_SIZE = 500

async def _try_authorized_pt_records(player_num: PlayerNum, player_id: int, start_time: datetime, end_time: datetime, room_rank: AbstractSet[RoomRank], limit: int) -> list[GameRecord]:
    api_key = normalize_api_key(conf.majsoul_paifuya_api_key)
    if not api_key:
        raise QueryError(PT_KEY_REQUIRED)
    records = []
    cursor = end_time
    try:
        while len(records) < limit and cursor >= start_time:
            batch_size = min(PLAYER_RECORDS_BATCH_SIZE, limit - len(records))
            try:
                page = await api[player_num].player_records(
                    player_id, start_time, cursor, room_rank,
                    limit=batch_size, descending=True, api_key=api_key,
                )
            except HTTPStatusError as exc:
                if records and exc.response.status_code == 404:
                    break
                raise
            records.extend(page[:batch_size])
            if len(page) < batch_size or len(records) >= limit:
                break
            next_cursor = page[-1].start_time - timedelta(seconds=1)
            if next_cursor >= cursor:
                raise QueryError('牌谱屋分页未向前推进，请稍后重试')
            cursor = next_cursor
    except (HTTPError, PaifuyaRateLimitError) as e:
        logger.warning('Paifuya authorized PT request failed (%s); no anonymous fallback', type(e).__name__)
        raise
    return records[:limit]

def draw(bio: BytesIO, player_num: PlayerNum, player: PlayerInfo, initial_level: PlayerLevel, records: Sequence[GameRecord]):
    # Restore the original font setup at draw time, after other plugins' styles.
    font_path = str(Path(conf.majsoul_font_path) if conf.majsoul_font_path
                    else Path(__file__).parent / 'NotoSansCJK-Regular.otf')
    font_manager.fontManager.addfont(font_path)
    font_name = font_manager.FontProperties(fname=font_path).get_name()
    plt.rcParams['font.family'] = font_name
    plt.rcParams['axes.unicode_minus'] = False
    fig: Figure = plt.figure(facecolor='w', figsize=(16, 10))
    ax: Axes = fig.add_subplot(1, 1, 1)
    pre_rank = max_rank = initial_level.id
    pre_pt = pt = initial_level.score + initial_level.delta
    base = pre_rank.max_pt // 2
    ax.text(3, 100, '\n'.join(map_player_rank(pre_rank)), fontsize=15)
    is_celestial = False
    for i, r in enumerate(records):
        for p in r.players:
            if p.id != player.id:
                continue
            rank = p.rank
            if max_rank is None or rank > max_rank:
                max_rank = rank
            if pre_rank != rank:
                ax.text(i + 3, 100, '\n'.join(map_player_rank(rank)), fontsize=15)
                ax.vlines(i, 0, max(rank.max_pt, pre_rank.max_pt if pre_rank else 0), color='k')
                base = rank.max_pt // 2
                pt = pre_pt = base
            if rank.major_rank == PlayerMajorRank.celestial:
                pt += p.pt * 5
                is_celestial = True
            else:
                pt += p.pt
            ax.plot([i, i + 1], [pre_pt, pt], color='k', lw=1.5)
            ax.fill_between([i, i + 1], [pre_pt, pt], color=_color[r.room_rank], alpha=0.05)
            ax.plot([i, i + 1], [base, base], color='k', lw=1.5)
            ax.plot([i, i + 1], [base * 2, base * 2], color='k', lw=1.5)
            pre_rank, pre_pt = (rank, pt)
    ax.set_title(f"雀魂段位战PT推移图[{map_player_num(player_num)}]  @{player.nickname}（{records[0].start_time.strftime('%Y/%m/%d')}~{records[-1].start_time.strftime('%Y/%m/%d')}）", fontsize=12, pad=5)
    ax.set_xlabel('对局数', fontsize=20)
    ax.set_ylabel('PT', fontsize=20)
    if not is_celestial:
        ax.set_yticks([i * 1000 for i in range(11)], labels=[i * 1000 for i in range(11)])
    else:
        ax.set_yticks([i * 1000 for i in range(11)], labels=[f'{i * 1000} 魂珠{float(i * 2)}' for i in range(11)])
    ax.set_xlim(0, len(records))
    ax.set_ylim(0, max_rank.max_pt + 100)
    # Bind the exact file, even if another registered font has the same family.
    for text in fig.findobj(match=PlotText):
        properties = text.get_fontproperties().copy()
        properties.set_file(font_path)
        text.set_fontproperties(properties)
    fig.savefig(bio, format='png')
    plt.close(fig)

async def handle_majsoul_pt_plot(emit, nickname: str, player_num: PlayerNum, *, room_rank: Optional[AbstractSet[RoomRank]]=None, start_time: Optional[datetime]=None, end_time: Optional[datetime]=None, limit: Optional[int]=None):
    if not conf.pt_query_enabled:
        raise QueryError(PT_KEY_REQUIRED)
    if room_rank is None:
        if player_num == PlayerNum.four:
            room_rank = all_four_player_room_rank
        elif player_num == PlayerNum.three:
            room_rank = all_three_player_room_rank
        else:
            raise ValueError(f'invalid player_num: {player_num}')
    if end_time is None:
        end_time = datetime.now(timezone.utc)
    players = await api[player_num].search_player(nickname)
    players = [p for p in players if p.nickname == nickname]
    if len(players) == 0:
        raise QueryError('没有查询到该角色在金之间以上的对局数据呢~')
    if start_time is None:
        api_start_time = datetime.fromisoformat('2010-01-01T00:00:00').astimezone(timezone.utc)
    else:
        api_start_time = start_time
    plot_limit = min(limit or conf.majsoul_pt_max_games, conf.majsoul_pt_max_games)
    sent_any = False
    for player in players:

        try:
            records = await _try_authorized_pt_records(player_num, player.id, api_start_time, end_time, room_rank, plot_limit)
            records.reverse()
        except HTTPStatusError as e:
            if e.response.status_code != 404:
                raise e
            continue
        if not records:
            continue
        initial_level = None
        for p in records[0].players:
            if p.id == player.id:
                initial_level = PlayerLevel(id=p.rank, score=p.rank.max_pt // 2, delta=0)
                break
        if initial_level is None:
            continue
        msg = f'昵称：{player.nickname} (id={player.id})\n对局数：{len(records)}'
        with BytesIO() as bio:
            await run_in_my_executor(draw, bio, player_num, player, initial_level, records)
            await emit([Text(msg), Image(bio.getvalue())])
        sent_any = True
    if not sent_any:
        raise QueryError('所有同名账号均没有有效对局数据')

_color = {RoomRank.four_player_throne_south: 'r', RoomRank.four_player_throne_east: 'r', RoomRank.four_player_jade_south: 'g', RoomRank.four_player_jade_east: 'g', RoomRank.four_player_golden_south: 'y', RoomRank.four_player_golden_east: 'y', RoomRank.three_player_throne_south: 'r', RoomRank.three_player_throne_east: 'r', RoomRank.three_player_jade_south: 'g', RoomRank.three_player_jade_east: 'g', RoomRank.three_player_golden_south: 'y', RoomRank.three_player_golden_east: 'y'}
