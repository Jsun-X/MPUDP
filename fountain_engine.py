"""统一喷泉编解码入口：linear（实验） / lt（GF(2) XOR LT） / raptorq（RFC6330，可选）。"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from fountain_codec import EncodedPacket, decode_from_packets, random_encoded_packet
from lt_fountain import LTEncoder, LTDecoder, LTPacket, split_message
from raptorq_codec import HAS_RAPTORQ, RaptorQDecoder, RaptorQEncoder


class FountainEngine(ABC):
    @abstractmethod
    def next_datagram(self) -> Dict[str, Any]: ...

    @abstractmethod
    def metadata(self) -> Dict[str, Any]: ...


class LinearEngine(FountainEngine):
    def __init__(self, source: List[float], block_id: int, rng_seed: int) -> None:
        import random

        self.k = len(source)
        self.source = source
        self.block_id = block_id
        self.rng = random.Random(rng_seed)
        self.seq = 0

    def metadata(self) -> Dict[str, Any]:
        return {"codec": "linear", "k": self.k, "block_id": self.block_id}

    def next_datagram(self) -> Dict[str, Any]:
        pkt = random_encoded_packet(self.k, self.source, self.rng)
        body = {"type": "fountain", "codec": "linear", "block_id": self.block_id, "seq": self.seq, "k": self.k, **pkt.to_dict()}
        self.seq += 1
        return body


class LTEngine(FountainEngine):
    def __init__(self, message: bytes, symbol_size: int, block_id: int, seed: int) -> None:
        self.symbols = split_message(message, symbol_size)
        self.k = len(self.symbols)
        self.symbol_size = symbol_size
        self.block_id = block_id
        self._enc = LTEncoder(self.symbols, block_id=block_id, seed=seed)
        self.raw_len = len(message)

    def metadata(self) -> Dict[str, Any]:
        return {
            "codec": "lt",
            "k": self.k,
            "symbol_size": self.symbol_size,
            "raw_len": self.raw_len,
            "block_id": self.block_id,
        }

    def next_datagram(self) -> Dict[str, Any]:
        p = self._enc.next_packet()
        return {
            "type": "fountain",
            "codec": "lt",
            "block_id": p.block_id,
            "esi": p.esi,
            "seed": p.seed,
            "degree": p.degree,
            "k": self.k,
            "raw_len": self.raw_len,
            "symbol_size": len(p.payload),
            "payload_b64": base64.b64encode(p.payload).decode("ascii"),
        }


class RaptorQEngine(FountainEngine):
    def __init__(self, message: bytes, symbol_size: int, block_id: int) -> None:
        if not HAS_RAPTORQ:
            raise RuntimeError("raptorq 未安装")
        self.message = message
        self.symbol_size = symbol_size
        self.block_id = block_id
        self._enc = RaptorQEncoder(message, symbol_size, block_id)

    def metadata(self) -> Dict[str, Any]:
        return {
            "codec": "raptorq",
            "symbol_size": self.symbol_size,
            "raw_len": len(self.message),
            "block_id": self.block_id,
            "k_source": self._enc.num_source_symbols,
        }

    def next_datagram(self) -> Dict[str, Any]:
        p = self._enc.next_packet()
        return {
            "type": "fountain",
            "codec": "raptorq",
            "block_id": p.block_id,
            "esi": p.esi,
            "symbol_size": len(p.payload),
            "raw_len": len(self.message),
            "payload_b64": base64.b64encode(p.payload).decode("ascii"),
        }


class FountainAccumulator:
    def __init__(self) -> None:
        self.codec: Optional[str] = None
        self.linear_packets: List[EncodedPacket] = []
        self.lt_decoder: Optional[LTDecoder] = None
        self.rq_decoder: Optional[RaptorQDecoder] = None
        self.k = 0
        self.raw_len = 0

    def ingest(self, msg: Dict[str, Any]) -> None:
        codec = msg.get("codec", "linear")
        if self.codec is None:
            self.codec = codec
        if codec == "linear":
            self.k = int(msg["k"])
            self.linear_packets.append(EncodedPacket.from_dict(msg))
        elif codec == "lt":
            if self.lt_decoder is None:
                self.k = int(msg["k"])
                sym = int(msg["symbol_size"])
                self.lt_decoder = LTDecoder(self.k, sym)
                self.raw_len = int(msg.get("raw_len", self.k * sym))
            payload = base64.b64decode(msg["payload_b64"])
            self.lt_decoder.add(
                LTPacket(
                    block_id=int(msg["block_id"]),
                    esi=int(msg["esi"]),
                    seed=int(msg["seed"]),
                    degree=int(msg["degree"]),
                    payload=payload,
                )
            )
        elif codec == "raptorq":
            if self.rq_decoder is None:
                sym = int(msg["symbol_size"])
                self.raw_len = int(msg["raw_len"])
                self.rq_decoder = RaptorQDecoder(sym, self.raw_len)
            payload = base64.b64decode(msg["payload_b64"])
            self.rq_decoder.add(payload)
        else:
            raise ValueError(f"unknown codec {codec}")

    def try_decode(self):
        if self.codec == "linear":
            import numpy as np

            d = decode_from_packets(self.linear_packets, self.k)
            return d.tolist() if d is not None else None
        if self.codec == "lt" and self.lt_decoder:
            raw = self.lt_decoder.try_decode()
            if raw is None:
                return None
            return raw[: self.raw_len]
        if self.codec == "raptorq" and self.rq_decoder:
            return self.rq_decoder.try_decode()
        return None

    def packet_count(self) -> int:
        if self.codec == "linear":
            return len(self.linear_packets)
        if self.lt_decoder:
            return len(self.lt_decoder.packets)
        if self.rq_decoder:
            return self.rq_decoder._count
        return 0
