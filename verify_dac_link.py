#!/usr/bin/env python3
"""
Verify point-to-point connectivity and TCP throughput between two hosts on the DAC / RoCE link.

From spark1.md / spark2.md (192.168.100.0/24):
  spark1: enp1s0f1np1 -> 192.168.100.11
  spark2: enp1s0f0np0 -> 192.168.100.12

Usage (example: spark1 = server, spark2 = client):
  On spark1:
    python3 verify_dac_link.py server --listen 192.168.100.11 --port 45231
  On spark2:
    python3 verify_dac_link.py client --peer 192.168.100.11 --local-bind 192.168.100.12 --port 45231

  Single-stream TCP in Python is often only a few–10s Gb/s (CPU bound). For high links use parallel streams:
    server: ... server --streams 16
    client: ... client --streams 16 ...

Optional link info (host shell, not inside minimal containers without ethtool):
    python3 verify_dac_link.py link-info --iface enp1s0f0np0

NCCL in Docker (brief):
  - "NET/IB : No device found" means the container sees no usable RDMA device. Your sample sets
    NCCL_IB_DISABLE=1 which disables IB; then NCCL uses TCP (NET/Socket) on NCCL_SOCKET_IFNAME.
  - To use IB/RoCE inside Docker you typically need devices passed in (e.g. --device /dev/infiniband/
    or --privileged), matching userspace (libmlx5), and NCCL_IB_DISABLE=0 with correct NCCL_IB_HCA.
  - For the DAC link here, bind NCCL_SOCKET_IFNAME to the netdev that carries 192.168.100.x
    (spark1: enp1s0f1np1, spark2: enp1s0f0np0), not the P2p interfaces.
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import threading
import time
from typing import Optional

DEFAULT_CHUNK = 4 * 1024 * 1024  # 4 MiB per send/recv


def _set_socket_opts(s: socket.socket) -> None:
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    for size in (256 * 1024 * 1024, 64 * 1024 * 1024, 16 * 1024 * 1024):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, size)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, size)
            break
        except OSError:
            continue


def _recv_until_eof(conn: socket.socket, chunk: int) -> int:
    buf = bytearray(chunk)
    total = 0
    while True:
        try:
            n = conn.recv_into(buf)
        except ConnectionResetError:
            break
        if n == 0:
            break
        total += n
    return total


def run_server(listen_host: str, port: int, chunk: int, streams: int) -> None:
    total_lock = threading.Lock()
    total_bytes = 0

    def handle(conn: socket.socket, addr: tuple[str, int], idx: int) -> None:
        nonlocal total_bytes
        with conn:
            _set_socket_opts(conn)
            n = _recv_until_eof(conn, chunk)
        with total_lock:
            total_bytes += n
        print(f"Stream {idx}/{streams} done from {addr[0]}:{addr[1]} ({n / 1e9:.3f} GB)", flush=True)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ls:
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind((listen_host, port))
        ls.listen(min(128, max(8, streams + 4)))
        print(
            f"Listening on {listen_host}:{port} (chunk={chunk} bytes, streams={streams})",
            flush=True,
        )
        t_wall0 = time.perf_counter()
        workers: list[threading.Thread] = []
        for i in range(streams):
            conn, addr = ls.accept()
            print(f"Accepted {i + 1}/{streams} from {addr[0]}:{addr[1]}", flush=True)
            t = threading.Thread(target=handle, args=(conn, addr, i + 1), daemon=True)
            workers.append(t)
            t.start()
        for t in workers:
            t.join()
        elapsed = time.perf_counter() - t_wall0
    gbps = (total_bytes * 8) / elapsed / 1e9 if elapsed > 0 else 0.0
    print(
        f"Received {total_bytes / 1e9:.4f} GB total in {elapsed:.3f} s wall -> {gbps:.2f} Gb/s (receiver view)",
        flush=True,
    )


def run_client(
    peer_host: str,
    port: int,
    duration_s: float,
    chunk: int,
    local_bind: Optional[str],
    streams: int,
) -> None:
    data = b"\0" * chunk
    barrier = threading.Barrier(streams)
    total_lock = threading.Lock()
    total_bytes = 0

    def worker(stream_id: int) -> None:
        nonlocal total_bytes
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if local_bind:
                s.bind((local_bind, 0))
            _set_socket_opts(s)
            s.connect((peer_host, port))
            barrier.wait()
            t0 = time.perf_counter()
            local = 0
            while time.perf_counter() < t0 + duration_s:
                s.sendall(data)
                local += len(data)
        with total_lock:
            total_bytes += local
        print(f"Stream {stream_id}/{streams} sent {local / 1e9:.4f} GB", flush=True)

    if local_bind:
        print(f"Bound local address {local_bind}", flush=True)
    print(
        f"Connecting {streams} TCP streams to {peer_host}:{port} ...",
        flush=True,
    )
    threads = [
        threading.Thread(target=worker, args=(i + 1,), daemon=True) for i in range(streams)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    gbps = (total_bytes * 8) / duration_s / 1e9 if duration_s > 0 else 0.0
    print(
        f"Sent {total_bytes / 1e9:.4f} GB aggregate in {duration_s:.3f} s window -> {gbps:.2f} Gb/s (sender view)",
        flush=True,
    )


def run_bidirectional(
    peer_host: str,
    port: int,
    duration_s: float,
    chunk: int,
    local_bind: Optional[str],
) -> None:
    """Both sides send simultaneously (run the same subcommand on both hosts)."""
    results: dict[str, float] = {}
    lock = threading.Lock()

    def sender(sock: socket.socket, label: str, t0: float) -> None:
        data = b"\0" * chunk
        total = 0
        t_end = t0 + duration_s
        while time.perf_counter() < t_end:
            sock.sendall(data)
            total += len(data)
        elapsed = time.perf_counter() - t0
        with lock:
            results[label] = (total * 8) / elapsed / 1e9 if elapsed > 0 else 0.0

    def receiver(sock: socket.socket, label: str, t0: float) -> None:
        buf = bytearray(chunk)
        total = 0
        t_end = t0 + duration_s
        while time.perf_counter() < t_end:
            try:
                sock.settimeout(min(0.2, max(0.0, t_end - time.perf_counter())))
                n = sock.recv_into(buf)
            except socket.timeout:
                continue
            if n == 0:
                break
            total += n
        elapsed = time.perf_counter() - t0
        with lock:
            results[label + "_rx"] = (total * 8) / elapsed / 1e9 if elapsed > 0 else 0.0

    assert local_bind is not None
    me = local_bind
    listen_side = socket.inet_aton(me) < socket.inet_aton(peer_host)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        _set_socket_opts(s)
        if listen_side:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((me, port))
            s.listen(1)
            print(f"Listening on {me}:{port} (bidirectional mode)", flush=True)
            conn, addr = s.accept()
            print(f"Peer connected from {addr}", flush=True)
            peer = conn
        else:
            s.bind((me, 0))
            print(f"Connecting to {peer_host}:{port} ...", flush=True)
            s.connect((peer_host, port))
            peer = s

        with peer:
            _set_socket_opts(peer)
            print(f"Bidirectional flood for {duration_s} s ...", flush=True)
            start_evt = threading.Event()

            def sender_sync(sock: socket.socket, label: str) -> None:
                start_evt.wait()
                t0 = time.perf_counter()
                sender(sock, label, t0)

            def receiver_sync(sock: socket.socket, label: str) -> None:
                start_evt.wait()
                t0 = time.perf_counter()
                receiver(sock, label, t0)

            t_send = threading.Thread(target=sender_sync, args=(peer, "tx"))
            t_recv = threading.Thread(target=receiver_sync, args=(peer, "rx"))
            t_recv.start()
            t_send.start()
            t_wall0 = time.perf_counter()
            start_evt.set()
            t_send.join()
            t_recv.join(timeout=duration_s + 2.0)
            wall = time.perf_counter() - t_wall0
        print(f"Wall time ~{wall:.3f} s", flush=True)
        for k, v in sorted(results.items()):
            print(f"  {k}: {v:.2f} Gb/s", flush=True)


def run_link_info(iface: str) -> None:
    try:
        out = subprocess.run(
            ["ethtool", iface],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        print("ethtool not found; install iproute2/ethtool or run on the host.", file=sys.stderr)
        sys.exit(1)
    if out.returncode != 0:
        print(out.stderr or out.stdout, file=sys.stderr)
        sys.exit(out.returncode)
    text = out.stdout
    speed_m = re.search(r"Speed:\s*(\S+)", text)
    link_m = re.search(r"Link detected:\s*(\S+)", text)
    print(text)
    if speed_m:
        print(f"--- parsed Speed: {speed_m.group(1)}", flush=True)
    if link_m:
        print(f"--- parsed Link detected: {link_m.group(1)}", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description="DAC / RoCE link connectivity and TCP throughput check")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("server", help="Receive bytes from client and report receive throughput")
    ps.add_argument("--listen", default="0.0.0.0", help="Address to bind (use your 192.168.100.x IP)")
    ps.add_argument("--port", type=int, default=45231)
    ps.add_argument("--chunk", type=int, default=DEFAULT_CHUNK, help="Bytes per recv()")
    ps.add_argument(
        "--streams",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel TCP connections to accept (must match client)",
    )

    pc = sub.add_parser("client", help="Send to server for fixed duration")
    pc.add_argument("--peer", required=True, help="Remote 192.168.100.x address")
    pc.add_argument("--port", type=int, default=45231)
    pc.add_argument("--duration", type=float, default=10.0, help="Seconds to send")
    pc.add_argument("--chunk", type=int, default=DEFAULT_CHUNK, help="Bytes per send()")
    pc.add_argument(
        "--streams",
        type=int,
        default=1,
        metavar="N",
        help="Parallel TCP connections (reduces single-thread CPU bottleneck on fast links)",
    )
    pc.add_argument(
        "--local-bind",
        default=None,
        help="Local source IP (use your side's 192.168.100.x to force traffic on the DAC)",
    )

    pb = sub.add_parser(
        "bidir",
        help="Run on BOTH nodes: simultaneous send/receive on one TCP connection (same --port)",
    )
    pb.add_argument("--peer", required=True, help="The other host's 192.168.100.x")
    pb.add_argument("--port", type=int, default=45231)
    pb.add_argument("--duration", type=float, default=10.0)
    pb.add_argument("--chunk", type=int, default=DEFAULT_CHUNK)
    pb.add_argument("--local-bind", default=None, help="This host's 192.168.100.x (required for role)")

    pl = sub.add_parser("link-info", help="Print ethtool speed/link for an interface (host only)")
    pl.add_argument("--iface", required=True)

    pt = sub.add_parser("ping-tcp", help="Try TCP connect to host:port (quick connectivity check)")
    pt.add_argument("--peer", required=True)
    pt.add_argument("--port", type=int, default=45231)

    args = p.parse_args()

    if args.cmd == "server":
        run_server(args.listen, args.port, args.chunk, args.streams)
    elif args.cmd == "client":
        run_client(
            args.peer,
            args.port,
            args.duration,
            args.chunk,
            args.local_bind,
            args.streams,
        )
    elif args.cmd == "bidir":
        if not args.local_bind:
            print("bidir requires --local-bind <this host 192.168.100.x>", file=sys.stderr)
            sys.exit(1)
        run_bidirectional(args.peer, args.port, args.duration, args.chunk, args.local_bind)
    elif args.cmd == "link-info":
        run_link_info(args.iface)
    elif args.cmd == "ping-tcp":
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3.0)
            err = s.connect_ex((args.peer, args.port))
            if err != 0:
                print(f"connect_ex -> {err} ({os_err(err)})", file=sys.stderr)
                sys.exit(1)
            print(f"TCP OK {args.peer}:{args.port}", flush=True)
    else:
        p.error("unknown command")


def os_err(code: int) -> str:
    try:
        return os.strerror(code)
    except Exception:
        return str(code)


if __name__ == "__main__":
    main()
