"""Run a parser over untrusted input in a separate process with a wall-clock timeout and an address-space cap.

The target must be a module-level function (it is pickled by reference). It returns a picklable result, or raises
`LimitExceeded` for an input-specific limit. Only the result, the limit message or the exception type name crosses
the process boundary."""

import multiprocessing as mp
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.context import ForkServerContext, SpawnContext
from typing import Any

PRELOAD = ["app.foundation.extraction", "app.foundation.files"]


class LimitExceeded(ValueError):
    """The input exceeded a time, memory or input-specific limit."""


class ChildFailed(ValueError):
    """The target raised; the message is the exception type name."""


def _limit_memory(max_bytes: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
    except (ImportError, ValueError, OSError):
        pass


def _caused_by_memory(e: BaseException | None) -> bool:
    while e is not None:
        if isinstance(e, MemoryError):
            return True
        e = e.__cause__ or e.__context__
    return False


def _entry(target: Callable[..., Any], args: tuple[Any, ...], conn: Connection, max_memory: int) -> None:
    """Child-process entry point: sends ("ok", result), ("limit", message) or ("error", type name)."""
    try:
        _limit_memory(max_memory)
        result = target(*args)
        conn.send(("ok", result))
    except LimitExceeded as e:
        conn.send(("limit", str(e)))
    except Exception as e:
        if _caused_by_memory(e):
            conn.send(("limit", "needs too much memory"))
        else:
            conn.send(("error", type(e).__name__))
    finally:
        conn.close()


def _mp_context() -> ForkServerContext | SpawnContext:
    if "forkserver" in mp.get_all_start_methods():
        ctx = mp.get_context("forkserver")
        ctx.set_forkserver_preload(PRELOAD)
        return ctx
    return mp.get_context("spawn")


def run(
    target: Callable[..., Any],
    *args: Any,
    timeout_seconds: float,
    max_memory_bytes: int,
    name: str = "sandbox",
) -> Any:
    ctx = _mp_context()
    recv, send = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_entry, args=(target, args, send, max_memory_bytes), name=name)
    proc.start()
    send.close()
    try:
        if not recv.poll(timeout_seconds):
            raise LimitExceeded(f"took longer than {timeout_seconds:g}s")
        msg = recv.recv()
    except EOFError:
        raise LimitExceeded("exceeded its resource limits") from None
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join()
        recv.close()
    if msg[0] == "ok":
        return msg[1]
    if msg[0] == "limit":
        raise LimitExceeded(msg[1])
    raise ChildFailed(msg[1])
