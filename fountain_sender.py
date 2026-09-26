#!/usr/bin/env python3
"""喷泉码 + 多路径 UDP 发送端：codec=linear | lt | raptorq。"""

from __future__ import annotations

import argparse
import random
import socket
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

from fountain_engine import LinearEngine, LTEngine, RaptorQEngine
from mpudp_protocol import pack_message, unpack_message
from raptorq_codec import HAS_RAPTORQ

Addr = Tuple[str, int]


class WeightedPathScheduler:
    def __init__(self, paths: Sequence[Addr], rng: random.Random) -> None:
        self.paths = list(paths)
        # 模式一：初始对各路径随机赋权（非均等 1.0），后续时段可由 adaptive 覆盖
        if len(self.paths) <= 1:
            self.weights = {self.paths[0]: 1.0}
        else:
            self.weights = {p: rng.uniform(0.2, 1.0) for p in self.paths}
        self._lock = threading.Lock()

    def update_weights(self, weights: Dict[Addr, float]) -> None:
        with self._lock:
            for p in self.paths:
                if p in weights:
                    self.weights[p] = max(float(weights[p]), 1e-6)

    def snapshot_weights(self) -> Dict[Addr, float]:
        with self._lock:
            return dict(self.weights)

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


def probe_rtt(sock: socket.socket, dest: Addr, timeout: float) -> Optional[float]:
    """向 dest 发探测包，接收端 echo，返回 RTT（秒）；失败返回 None。"""
    payload = pack_message({"type": "probe"})
    t0 = time.perf_counter()
    sock.sendto(payload, dest)
    sock.settimeout(timeout)
    try:
        data, _ = sock.recvfrom(2048)
        msg = unpack_message(data)
        if msg.get("type") == "probe_ack":
            return time.perf_counter() - t0
    except (socket.timeout, OSError, UnicodeDecodeError, ValueError, KeyError):
        return None
    return None


def measure_and_update_weights(
    paths: Sequence[Addr],
    probe_socks: Dict[Addr, socket.socket],
    scheduler: WeightedPathScheduler,
    probe_timeout: float,
) -> None:
    """按 RTT 倒数设权：延迟小（等效吞吐高）的路径权重大，发送概率高。"""
    weights: Dict[Addr, float] = {}
    info: List[str] = []
    for p in paths:
        rtt = probe_rtt(probe_socks[p], p, probe_timeout)
        if rtt is None:
            weights[p] = 0.05
            info.append(f":{p[1]} RTT=超时 w=0.05")
        else:
            weights[p] = 1.0 / max(rtt, 1e-4)
            info.append(f":{p[1]} RTT={rtt * 1000:.2f}ms w={weights[p]:.1f}")
    scheduler.update_weights(weights)
    print("本时段 RTT 测权 →", ", ".join(info))


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
    ap.add_argument("--message", default="MPUDP联合喷泉码-测试", help="lt/raptorq 待编码的源文本（仅发送端）")
    ap.add_argument("--symbol-size", type=int, default=16)
    ap.add_argument("--block-id", type=int, default=1)
    ap.add_argument("--max-packets", type=int, default=500)
    ap.add_argument("--ack-port", type=int, default=9101)
    ap.add_argument("--stagger", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--adaptive-weight",
        action="store_true",
        help="边发包边测 RTT：每个时段结束探测并调整权重（1/RTT）",
    )
    ap.add_argument(
        "--measure-interval",
        type=float,
        default=2.0,
        help="测权时段长度（秒）；每时段结束时探测各路径 RTT 并更新权重",
    )
    ap.add_argument("--probe-timeout", type=float, default=0.4, help="单次探测超时（秒）")
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

    scheduler = WeightedPathScheduler(paths, rng)
    if len(paths) > 1:
        print("初始权重（随机分配）:", scheduler.snapshot_weights())
    send_lock = threading.Lock()
    sockets = {p: socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for p in paths}
    probe_socks = {p: socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for p in paths}
    probe_lock = threading.Lock()

    if args.adaptive_weight and len(paths) > 1:
        print(
            f"已启用 adaptive-weight：边发编码包边测 RTT，"
            f"每 {args.measure_interval}s 为一个时段，时段末调整权重（∝ 1/RTT）"
        )
        print("[测权时段 0] 发送开始前先测一轮")
        with probe_lock:
            measure_and_update_weights(paths, probe_socks, scheduler, args.probe_timeout)

        def measure_loop() -> None:
            period = 1
            while not stop.wait(args.measure_interval):
                with probe_lock:
                    print(f"[测权时段 {period}] 并行发送中，探测 RTT 并更新下一时段权重")
                    measure_and_update_weights(
                        paths, probe_socks, scheduler, args.probe_timeout
                    )
                period += 1

        threading.Thread(target=measure_loop, daemon=True).start()

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
                w = scheduler.snapshot_weights()
                print(f"已发送 {sent} 包，最近路径 {path}，当前权重 {w}")
    finally:
        stop.set()
        for s in list(sockets.values()) + list(probe_socks.values()):
            s.close()

    elapsed = time.time() - t0
    print(f"发送结束: {sent} 包, {elapsed:.2f}s, {sent / max(elapsed, 1e-6):.1f} pkt/s")


if __name__ == "__main__":
    main()
