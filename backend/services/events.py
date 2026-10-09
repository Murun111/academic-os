"""In-process async pub/sub event hub.

Designed for use from the asyncio loop thread.  publish() is safe to call
with zero subscribers and never raises on a full queue (drops silently).
"""
import asyncio
import time

_subscribers: set[asyncio.Queue] = set()
# Server loop each queue belongs to, so publishes from foreign threads (e.g. the
# APScheduler thread running a cron agent) can wake it via call_soon_threadsafe.
_loops: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}


def subscribe() -> asyncio.Queue:
    """Create a bounded queue (maxsize 200), register it, and return it."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    try:
        _loops[q] = asyncio.get_running_loop()
    except RuntimeError:
        pass  # subscribed outside a loop; publish falls back to put_nowait
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Deregister a queue; no-op if it was never registered."""
    _subscribers.discard(q)
    _loops.pop(q, None)


def _put(q: asyncio.Queue, event: dict) -> None:
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        pass


def publish(event: dict) -> None:
    """Stamp ts if missing, then deliver event to every subscriber.

    Never raises.  A full subscriber queue causes the event to be dropped
    for that subscriber only; other subscribers are still notified.
    """
    if "ts" not in event:
        event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    for q in list(_subscribers):
        loop = _loops.get(q)
        try:
            if loop is not None and loop is not current:
                # Foreign thread (or another loop): put_nowait is not
                # thread-safe and would not wake the server loop.
                loop.call_soon_threadsafe(_put, q, event)
            else:
                q.put_nowait(event)
        except asyncio.QueueFull:
            pass
        except RuntimeError:
            pass  # loop closed


def subscriber_count() -> int:
    """Return the number of currently registered subscriber queues."""
    return len(_subscribers)
