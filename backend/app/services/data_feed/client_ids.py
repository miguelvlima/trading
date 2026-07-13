"""IBKR client-id allocation shared by the worker, WS sessions and engines.

The Gateway rejects a second session with a client id already in use (error
326 -> handshake timeout). Ids must therefore be unique across EVERY process
talking to the Gateway at once — a second uvicorn instance, a --reload
restart, or a stray duplicate backend. Plain per-process counters restart at
zero on every boot and hand out the same ids again, so each allocator seeds
its sequence with the current pid: distinct processes start from distinct
offsets and stay clear of each other.

Ranges (offsets from ``settings.ibkr_client_id``):
    worker (bar persistence)   base + 0..9
    realtime WS sessions       base + 10..209
    paper engine runtimes      base + 300..499
"""

from __future__ import annotations

import itertools
import os

_WS_SPAN = 200
_ENGINE_SPAN = 200
_WORKER_SPAN = 10

_ws_seq = itertools.count(os.getpid() % _WS_SPAN)
_engine_seq = itertools.count(os.getpid() % _ENGINE_SPAN)


def worker_client_id(base: int) -> int:
    """Polling worker id: one per process, pid-spread inside base+0..9."""
    return base + (os.getpid() % _WORKER_SPAN)


def next_ws_client_id(base: int) -> int:
    """Next realtime WS session id inside base+10..209."""
    return base + 10 + (next(_ws_seq) % _WS_SPAN)


def next_engine_client_id(base: int) -> int:
    """Next paper-engine runtime id inside base+300..499."""
    return base + 300 + (next(_engine_seq) % _ENGINE_SPAN)
