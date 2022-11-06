import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Tuple, Type, Union

from ..._typing import TTL, CallableCacheCondition
from ...backends.interface import _BackendInterface
from ...formatter import register_template
from ...key import get_cache_key, get_cache_key_template
from ...ttl import ttl_to_seconds
from .defaults import _empty, context_cache_detect

__all__ = ("soft",)


logger = logging.getLogger(__name__)


def soft(
    backend: _BackendInterface,
    ttl: TTL,
    key: Optional[str] = None,
    soft_ttl: Optional[TTL] = None,
    exceptions: Union[Type[Exception], Tuple[Type[Exception]]] = Exception,
    condition: CallableCacheCondition = lambda *args, **kwargs: True,
    prefix: str = "soft",
):
    """
    Cache strategy that allow to use pre-expiration

    :param backend: cache backend
    :param ttl: duration in seconds to store a result
    :param key: custom cache key, may contain alias to args or kwargs passed to a call
    :param condition: callable object that determines whether the result will be saved or not
    :param prefix: custom prefix for key, default 'early'
    """
    if soft_ttl is None:
        soft_ttl = ttl * 0.33  # type: ignore[assignment]

    def _decor(func):
        _key_template = get_cache_key_template(func, key=key, prefix=prefix)
        register_template(func, _key_template)

        @wraps(func)
        async def _wrap(*args, **kwargs):
            _ttl = ttl_to_seconds(ttl, *args, **kwargs)
            _soft_ttl = ttl_to_seconds(soft_ttl, *args, **kwargs)
            _cache_key = get_cache_key(func, _key_template, args, kwargs)
            cached = await backend.get(_cache_key, default=_empty)
            if cached is not _empty:
                soft_expire_at, result = cached
                if soft_expire_at > datetime.utcnow():
                    context_cache_detect._set(
                        _cache_key,
                        ttl=_ttl,
                        soft_ttl=_soft_ttl,
                        name="soft",
                        template=_key_template,
                    )
                    return result

            try:
                result = await func(*args, **kwargs)
            except exceptions:
                if cached is not _empty:
                    _, result = cached
                    context_cache_detect._set(
                        _cache_key,
                        ttl=_ttl,
                        soft_ttl=_soft_ttl,
                        name="soft",
                        template=_key_template,
                    )
                    return result
                raise
            else:
                if condition(result, args, kwargs, _cache_key):
                    soft_expire_at = datetime.utcnow() + timedelta(seconds=_soft_ttl)
                    await backend.set(_cache_key, [soft_expire_at, result], expire=_ttl)
                return result

        return _wrap

    return _decor
