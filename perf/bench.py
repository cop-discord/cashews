import time
import uuid
import random
import asyncio
from statistics import mean, pstdev

from cashews.backends import redis, client_side
from cashews import Cache
from aiocache import caches

prefix = str(uuid.uuid4())
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


def _key_static():
    return f"{prefix}:1"


def _key_random():
    return f"{prefix}:{random.randint(1, 1000)}"


async def set_big(backend, key):
    return await backend.set(key, [{"name": f"name_{i}", "id": i} for i in range(100)])


async def _get_latency(func, *args, **kwargs) -> float:
    start = time.perf_counter()
    await func(*args, **kwargs)
    return time.perf_counter() - start


async def run(target, test, test_name, iters=1000):
    try:
        await target.init()
    except (AttributeError, TypeError):
        pass

    method, key_gen, _options = test

    method = getattr(target, method)
    await target.clear()

    async def execute():
        options = dict(_options)
        key = key_gen()
        pre = options.pop("pre", None)
        if pre:
            if pre == "set":
                value = options.pop("value", "no_value")
                await target.set(key, value)
            else:
                await pre(target, key)
        return await _get_latency(method, key, **options)

    latencies = []
    for _ in range(iters):
        latencies.append(await execute())
    print("-" * 100)
    print(target, test_name)
    print("      max         ", "         mean        ", "      pstdev       ", )
    print(max(latencies), mean(latencies), pstdev(latencies))

caches.set_config({
    "default": {
        'cache':    "aiocache.RedisCache",
        'endpoint': "127.0.0.1",
        'port':     6379,
    },
    'redis_pickle': {
        'cache': "aiocache.RedisCache",
        'endpoint': "127.0.0.1",
        'port': 6379,
        'serializer': {
            'class': "aiocache.serializers.PickleSerializer"
        },
        'plugins': [
            {'class': "aiocache.plugins.HitMissRatioPlugin"},
            {'class': "aiocache.plugins.TimingPlugin"}
        ]
    }
})

if __name__ == '__main__':
    choices = input("""
    choose a backends
    1) aiocache simple
    2) aiocache pickle
    3) cashews hash 
    4) cashews no hash 
    5) cashews (wrapper) with stats
    6) cashews with client side bordcast
    7) cashews with client side update chan
    8) cashews with client side br wrapper and statistic
    """)
    backends = {
        1: caches.get("default"),
        2: caches.get("redis_pickle"),
        3: redis.Redis("redis://localhost/", hash_key=b"test"),
        4: redis.Redis("redis://localhost/", hash_key=None),
        5: Cache().setup("redis://localhost/", hash_key=b"f34feyhg;s23", count_stat=True),
        6: client_side.BcastClientSide("redis://localhost/", hash_key=None),
        7: client_side.UpdateChannelClientSide("redis://localhost/", hash_key=None),
        8: Cache().setup("redis://localhost/", hash_key="test", count_stat=True, client_side=True),
    }
    targets = []
    for choice in choices.split():
        targets.append(backends.get(int(choice)))

    choices = input("""
        choose a test
        1) get static key
        2) get random key
        3) get miss static key
        4) get miss random key
        5) set static key
        6) set random key
        7) incr static key
        8) incr random key
        9) del static key
        10) del random key
        11) get big object
    """)
    _tests = {
        1: ("get", _key_static, {"pre": "set", "value": object()}),
        2: ("get", _key_random, {"pre": "set", "value": "test"}),
        3: ("get", _key_static, {}),
        4: ("get", _key_random, {}),
        5: ("set", _key_static, {"value": b"simple"}),
        6: ("set", _key_random, {"value": b"simple"}),
        7: ("incr", _key_static, {}),
        8: ("incr", _key_random, {}),
        9: ("delete", _key_static, {}),
        10: ("delete", _key_random, {}),
        11: ("get", _key_static, {"pre": set_big}),
    }
    tests = []
    for choice in choices.split():
        tests.append((choice, _tests.get(int(choice))))

    iters = int(input("Iters: ") or "1000")

    for test in tests:
        print("--------------------TEST---------------------")
        for target in targets:
            loop.run_until_complete(run(target, test[1], test[0], iters=iters))
