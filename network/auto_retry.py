from asyncio import sleep
from functools import wraps
from typing import TypeVar, Callable, Optional, Awaitable, Any, Union, Type, Sequence

from astrbot.api import logger
from typing_extensions import ParamSpec

T = TypeVar('T')
P = ParamSpec('P')


def auto_retry(error: Union[Type[Exception], Sequence[Type[Exception]]],
               before_retry: Optional[Callable[[], Awaitable[Any]]] = None,
               *,
               attempts: int = 10,
               retry_if: Optional[Callable[[Exception], bool]] = None,
               retry_delay: Optional[Callable[[Exception, int], float]] = None):
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except error as e:
                    if retry_if is not None and not retry_if(e):
                        raise

                    if attempt == attempts:
                        raise

                    delay = max(0.0, retry_delay(e, attempt) if retry_delay else 0.0)
                    logger.warning(
                        f"Retrying... {attempt}/{attempts - 1} in {delay:g}s "
                        f"({type(e).__name__}: {e})"
                    )

                    if delay:
                        await sleep(delay)

                    if before_retry:
                        try:
                            await before_retry()
                        except error as e2:
                            logger.warning(
                                f"Error occurred while preparing retry {attempt}/{attempts - 1} "
                                f"({type(e2).__name__}: {e2})"
                            )

        return wrapper

    return decorator
