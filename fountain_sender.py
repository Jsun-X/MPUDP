#!/usr/bin/env python3
"""喷泉码 + 多路径 UDP 发送端：codec=linear | lt | raptorq。"""

from __future__ import annotations

import argparse
import random
import socket
import threading
import time
from typing import List, Sequence, Tuple

from fountain_engine import LinearEngine, LTEngine, RaptorQEngine
from mpudp_protocol import pack_message
from raptorq_codec import HAS_RAPTORQ

Addr = Tuple[str, int]


class WeightedPathScheduler:
    def __init__(self, paths: Sequence[Addr]) -> None:
        self.paths = list(paths)
        self.weights = {p: 1.0 for p in self.paths}
        self._lock = threading.Lock()

    def next_path(self, rng: random.Random) -> Addr:
        with self._lock:
            total = sum(self.weights[p] for p in self.paths)
            r = rng.uniform(0, total)
            acc = 0.0
            for p in self.paths:
                acc += self.weights[p]
                if acc >= r:
                    return p
            return self.paths[-1]


def parse_paths(s: str) -> List[Addr]:
    out: List[Addr] = []
    for part in s.split(","):
        host, port = part.rsplit(":", 1)
        out.append((host.strip(), int(port)))
    return out


def build_engine(args: argparse.Namespace):
    if args.codec == "linear":
        source = [float(x.strip()) for x in args.source.split(",")]
        return LinearEngine(source, args.block_id, args.seed)
    if args.codec == "lt":
        msg = args.message.encode("utf-8")
        return LTEngine(msg, args.symbol_size, args.block_id, args.seed)
    if args.codec == "raptorq":
        return RaptorQEngine(args.message.encode("utf-8"), args.symbol_size, args.block_id)
    raise ValueError(args.codec)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fountain UDP sender (MPUDP)")
    ap.add_argument("--codec", choices=["linear", "lt", "raptorq"], default="lt")
    ap.add_argument("--paths", default="127.0.0.1:9000")
    ap.add_argument("--source", default="1,2,3,4,5,6,7,8", help="linear 模式源向量")
    ap.add_argument("--message", default="MPUDP LT/RaptorQ 实验载荷-payload", help="lt/raptorq 源消息")
    ap.add_argument("--symbol-size", type=int, default=16)
    ap.add_argument("--block-id", type=int, default=1)
    ap.add_argument("--max-packets", type=int, default=500)
    ap.add_argument("--ack-port", type=int, default=9101)
    ap.add_argument("--stagger", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.codec == "raptorq" and not HAS_RAPTORQ:
        raise SystemExit("raptorq 未安装：python3 -m pip install raptorq 后使用 --codec raptorq")

    paths = parse_paths(args.paths)
    engine = build_engine(args)
    meta = engine.metadata()
    print("发送配置:", meta)

    rng = random.Random(args.seed)
    stop = threading.Event()

    def listen_ack() -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", args.ack_port))
        sock.settimeout(0.5)
        while not stop.is_set():
            try:
                data, _ = sock.recvfrom(2048)
                if data.decode(errors="ignore").startswith("ACK"):
                    print("收到接收端 ACK，停止发送")
                    stop.set()
                    break
            except socket.timeout:
                continue
        sock.close()

    threading.Thread(target=listen_ack, daemon=True).start()

    scheduler = WeightedPathScheduler(paths)
    send_lock = threading.Lock()
    sockets = {p: socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for p in paths}

    sent = 0
    t0 = time.time()
    try:
        for _ in range(args.max_packets):
            if stop.is_set():
                break
            body = engine.next_datagram()
            path = scheduler.next_path(rng)
            payload = pack_message(body)

            def _send() -> None:
                sockets[path].sendto(payload, path)

            if args.stagger and len(paths) > 1:
                with send_lock:
                    _send()
            else:
                _send()

            sent += 1
            if sent % 25 == 0:
                print(f"已发送 {sent} 包，路径 {path}")
    finally:
        for s in sockets.values():
            s.close()

    elapsed = time.time() - t0
    print(f"发送结束: {sent} 包, {elapsed:.2f}s, {sent / max(elapsed, 1e-6):.1f} pkt/s")
    stop.set()


if __name__ == "__main__":
    main()
