"""
Echo websocket server that ALSO drops the underlying TCP socket without
sending a Close frame after WS_IDLE_KILL_SECONDS.

The clean-vs-flaky distinction is the whole point: a normal server
sends a 1000 (Normal Closure) frame before tearing down TCP; this
one yanks the rug out, which is exactly the wild-internet failure
mode (mobile NAT idle timeout, load balancer worker recycle,
container OOM-kill, ...) that operators actually hit.

Listen on :8080 over plain TCP -- TLS-wrapped websockets are not
needed to demonstrate the failure mode and would force us to drag
the cert-gen story into yet another image.
"""

from __future__ import annotations

import asyncio
import os
import socket

import websockets


IDLE_KILL = float(os.environ.get("WS_IDLE_KILL_SECONDS", "3"))


async def handler(ws):
    """Echo received frames; after IDLE_KILL seconds force-close the TCP socket."""
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_echo(ws))
            tg.create_task(_kill_after(ws))
    except* Exception:
        # Whichever task ended first will cancel the other; we don't care
        # about its exception value -- the test cares about the wire side.
        pass


async def _echo(ws):
    async for msg in ws:
        await ws.send(msg)


async def _kill_after(ws):
    await asyncio.sleep(IDLE_KILL)
    # Reach into the underlying transport and SO_LINGER=0 + close, which
    # makes the kernel send TCP RST instead of a graceful FIN. This is
    # the wire signature most observable from a pcap.
    sock: socket.socket | None = ws.transport.get_extra_info("socket") if ws.transport else None
    if sock is not None:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                            int(1).to_bytes(2, "little") + int(0).to_bytes(2, "little"))
        except OSError:
            pass
    if ws.transport is not None:
        ws.transport.abort()
    print(f"[ws-flaky] force-killed connection after {IDLE_KILL}s", flush=True)


async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("[ws-flaky] listening on :8080", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
