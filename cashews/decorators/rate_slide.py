from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, NoReturn

from cashews.backends.interface import _BackendInterface
from cashews.exceptions import RateLimitError
from cashews.key import get_cache_key, get_cache_key_template
from cashews.ttl import ttl_to_seconds

if TYPE_CHECKING:  # pragma: no cover
    from cashews._typing import TTL, DecoratedFunc, KeyOrTemplate

logger = logging.getLogger(__name__)


def _default_action(*args: Any, **kwargs: Any) -> NoReturn:
    raise RateLimitError()


def slice_rate_limit(
    backend: _BackendInterface,
    limit: int,
    period: TTL,
    key: KeyOrTemplate | None = None,
    action: Callable | None = _default_action,
    prefix: str = "srate",
) -> Callable[[DecoratedFunc], DecoratedFunc]:  # pylint: disable=too-many-arguments
    """
    Rate limit for function call. Do not call function if rate limit is reached, and call given action

    :param backend: cache backend
    :param limit: number of calls
    :param period: Period
    :param key: a rate-limit key template
    :param action: call when rate limit reached, default raise RateLimitError
    :param prefix: custom prefix for key, default 'rate_limit'
    """
    period = ttl_to_seconds(period)
    action = action or _default_action

    def decorator(func: DecoratedFunc) -> DecoratedFunc:
        _key_template = get_cache_key_template(func, key=key, prefix=prefix)

        @wraps(func)
        async def wrapped_func(*args, **kwargs):
            _period = ttl_to_seconds(period, *args, **kwargs, with_callable=True)
            _cache_key = get_cache_key(func, _key_template, args, kwargs)

            requests_count = await _get_requests_count(backend, _cache_key, limit, _period)
            if requests_count and requests_count > limit:
                logger.info("Rate limit reach for %s", _cache_key)
                action(*args, **kwargs)
            return await func(*args, **kwargs)

        return wrapped_func  # type: ignore[return-value]

    return decorator


async def _get_requests_count(backend: _BackendInterface, key: str, limit: int, period: int) -> int:
    timestamp = datetime.now(timezone.utc).timestamp()
    return await backend.slice_incr(key, timestamp - period, timestamp, maxvalue=limit + 1, expire=period)
