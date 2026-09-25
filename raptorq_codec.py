"""
RaptorQ (RFC 6330) 封装：依赖 PyPI `raptorq`（Rust 实现，GF(2^8) 完整算术）。
未安装时 import 失败，发送端应回退到 `--codec lt`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

try:
    import raptorq  # type: ignore

    HAS_RAPTORQ = True
except ImportError:
    raptorq = None  # type: ignore
    HAS_RAPTORQ = False


@dataclass
class RaptorQPacket:
    block_id: int
    esi: int
    payload: bytes


class RaptorQEncoder:
    def __init__(self, data: bytes, symbol_size: int, block_id: int = 1) -> None:
        if not HAS_RAPTORQ:
            raise RuntimeError("未安装 raptorq，请执行: python3 -m pip install raptorq")
        self.block_id = block_id
        self.data = data
        self.symbol_size = symbol_size
        self._enc = raptorq.Encoder.with_defaults(data, symbol_size)
        self.esi = 0

    @property
    def num_source_symbols(self) -> int:
        return self._enc.num_symbols()

    def next_packet(self) -> RaptorQPacket:
        payload = bytes(self._enc.encode(self.esi))
        pkt = RaptorQPacket(block_id=self.block_id, esi=self.esi, payload=payload)
        self.esi += 1
        return pkt


class RaptorQDecoder:
    def __init__(self, symbol_size: int, data_len: int) -> None:
        if not HAS_RAPTORQ:
            raise RuntimeError("未安装 raptorq")
        self.symbol_size = symbol_size
        self.data_len = data_len
        self._dec = raptorq.Decoder.with_defaults(symbol_size, data_len)
        self._count = 0

    def add(self, payload: bytes) -> None:
        self._dec.add(payload)
        self._count += 1

    def try_decode(self) -> Optional[bytes]:
        result = self._dec.decode()
        if result is None:
            return None
        return bytes(result)
