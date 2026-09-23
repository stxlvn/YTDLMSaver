from src.handlers.download_handlers import _SelectionCache


def test_selection_cache_scopes_by_chat_id():
    # Telegram message ids are per-chat counters, so two different chats can
    # legitimately share the same numeric id — the cache must not confuse them.
    cache = _SelectionCache()
    cache[(111, 42)] = {"url": "chat-a-video"}
    cache[(222, 42)] = {"url": "chat-b-video"}

    assert cache[(111, 42)]["url"] == "chat-a-video"
    assert cache[(222, 42)]["url"] == "chat-b-video"


def test_selection_cache_evicts_oldest_past_cap():
    cache = _SelectionCache()
    cache._MAX = 3
    for i in range(5):
        cache[(1, i)] = i

    assert len(cache) == 3
    assert (1, 0) not in cache
    assert (1, 1) not in cache
    assert cache[(1, 4)] == 4


def test_selection_cache_update_does_not_evict():
    cache = _SelectionCache()
    cache._MAX = 2
    cache[(1, 1)] = "a"
    cache[(1, 2)] = "b"
    cache[(1, 1)] = "a2"  # re-set an existing key must not trigger eviction

    assert len(cache) == 2
    assert cache[(1, 1)] == "a2"
    assert cache[(1, 2)] == "b"
