import re
from typing import Optional

from ...errors import BadRequestError
from cn2an import cn2an

def decode_integer(value):
    return int(value) if value.isdigit() else int(cn2an(value, "smart"))



def try_parse_limit_of_games(raw: str) -> Optional[int]:
    result = re.match(r"^最近(.*)场$$", raw)
    if result is not None:
        num = result.group(1)
        try:
            num = decode_integer(num)
        except ValueError:
            return None

        if num <= 0:
            raise BadRequestError("场数不合法")

        return num

    return None
