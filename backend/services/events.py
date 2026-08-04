"""In-process async pub/sub event hub.

Designed for use from the asyncio loop thread.  publish() is safe to call
with zero subscribers and never raises on a full queue (drops silently).
"""
import asyncio
import time

_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    """Create a bounded queue (maxsize 200), register it, and return it."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Deregister a queue; no-op if it was never registered."""
    _subscribers.discard(q)


def publish(event: dict) -> None:
    """Stamp ts if missing, then deliver event to every subscriber.

    Never raises.  A full subscriber queue causes the event to be dropped
    for that subscriber only; other subscribers are still notified.
    """
    if "ts" not in event:
        event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def subscriber_count() -> int:
    """Return the number of currently registered subscriber queues."""
    return len(_subscribers)
