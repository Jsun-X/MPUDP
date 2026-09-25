#!/usr/bin/env python3
"""喷泉码 UDP 接收端：多端口汇聚 + LT/RaptorQ/linear 解码。"""

from __future__ import annotations

import argparse
import socket
import threading
from typing import List, Tuple

from fountain_engine import FountainAccumulator
from mpudp_protocol import unpack_message

Addr = Tuple[str, int]


def parse_ports(s: str) -> List[int]:
    return [int(p.strip()) for p in s.split(",")]


def main() -> None:
    ap = argparse.ArgumentParser(description="Fountain UDP receiver (MPUDP)")
    ap.add_argument("--ports", default="9000")
    ap.add_argument("--sender-ack", default="127.0.0.1:9101")
    ap.add_argument("--max-packets", type=int, default=2000)
    args = ap.parse_args()

    listen_ports = parse_ports(args.ports)
    ack_host, ack_port_s = args.sender_ack.rsplit(":", 1)
    ack_addr: Addr = (ack_host.strip(), int(ack_port_s))

    acc = FountainAccumulator()
    acc_lock = threading.Lock()
    done = threading.Event()

    def worker(port: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", port))
        print(f"监听 0.0.0.0:{port}")
        while not done.is_set():
            sock.settimeout(1.0)
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            if done.is_set():
                break
            try:
                msg = unpack_message(data)
            except (UnicodeDecodeError, ValueError, KeyError):
                continue
            if msg.get("type") != "fountain":
                continue
            with acc_lock:
                if done.is_set():
                    break
                acc.ingest(msg)
                n = acc.packet_count()
                decoded = acc.try_decode()
            if n % 20 == 0:
                print(f"已收 {n} 包 (端口 {port}, 来自 {addr})")
            if decoded is not None:
                with acc_lock:
                    if done.is_set():
                        break
                    preview = decoded if isinstance(decoded, (bytes, bytearray)) else decoded
                    print("解码成功:", preview)
                    sock.sendto(b"ACK:ok", ack_addr)
                    done.set()
                break
            if n >= args.max_packets:
                with acc_lock:
                    if not done.is_set():
                        print("达到 max-packets 仍未解码")
                        done.set()
                break
        sock.close()

    threads = [threading.Thread(target=worker, args=(p,), daemon=True) for p in listen_ports]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
