"""
LT 喷泉码（工程实现）：按字节 XOR 组合源符号；度分布 Robust Soliton；
解码：剥洋葱 (BP)，失败时用 GF(2) 按位高斯消元。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import numpy as np


def robust_soliton_cdf(k: int, c: float = 0.1, delta: float = 0.5) -> List[float]:
    s = c * np.log(k / delta) * np.sqrt(k)
    rho = np.zeros(k + 1)
    rho[1] = 1.0 / k
    for d in range(2, k):
        rho[d] = 1.0 / (d * (d - 1))
    tau = np.zeros(k + 1)
    for d in range(1, k + 1):
        if d < k / s:
            tau[d] = s / (k * d)
        elif d == int(k / s):
            tau[d] = s * np.log(s / delta) / k
        else:
            tau[d] = 0.0
    mu = (rho + tau) / np.sum(rho + tau)
    return np.cumsum(mu).tolist()


def sample_degree(k: int, rng: random.Random, cdf: List[float]) -> int:
    u = rng.random()
    for d in range(1, k + 1):
        if u <= cdf[d]:
            return d
    return k


def indices_from_seed(k: int, d: int, seed: int) -> Tuple[int, ...]:
    rng = random.Random(seed)
    chosen: Set[int] = set()
    while len(chosen) < d:
        chosen.add(rng.randrange(k))
    return tuple(sorted(chosen))


@dataclass
class LTPacket:
    block_id: int
    esi: int
    seed: int
    degree: int
    payload: bytes


class LTEncoder:
    def __init__(
        self,
        source_symbols: List[bytes],
        block_id: int = 1,
        c: float = 0.1,
        delta: float = 0.5,
        seed: int = 42,
    ) -> None:
        self.k = len(source_symbols)
        if self.k == 0:
            raise ValueError("empty source")
        sym_len = len(source_symbols[0])
        if any(len(s) != sym_len for s in source_symbols):
            raise ValueError("symbol size mismatch")
        self.source = source_symbols
        self.block_id = block_id
        self.cdf = robust_soliton_cdf(self.k, c, delta)
        self.rng = random.Random(seed)
        self.esi = 0

    def next_packet(self) -> LTPacket:
        d = sample_degree(self.k, self.rng, self.cdf)
        seed = self.rng.getrandbits(32)
        idx = indices_from_seed(self.k, d, seed)
        payload = bytearray(len(self.source[0]))
        for i in idx:
            for j in range(len(payload)):
                payload[j] ^= self.source[i][j]
        pkt = LTPacket(
            block_id=self.block_id,
            esi=self.esi,
            seed=seed,
            degree=d,
            payload=bytes(payload),
        )
        self.esi += 1
        return pkt


class LTDecoder:
    def __init__(self, k: int, symbol_size: int) -> None:
        self.k = k
        self.symbol_size = symbol_size
        self.packets: List[LTPacket] = []

    def add(self, pkt: LTPacket) -> None:
        if len(pkt.payload) != self.symbol_size:
            raise ValueError("symbol size mismatch")
        self.packets.append(pkt)

    def try_decode(self) -> Optional[bytes]:
        if len(self.packets) < self.k:
            return None
        out = self._peel_decode()
        if out is not None:
            return out
        return self._ge_bit_decode()

    def _peel_decode(self) -> Optional[bytes]:
        k, sym = self.k, self.symbol_size
        known: Dict[int, bytearray] = {}
        checks: List[Tuple[Set[int], bytearray]] = []
        for p in self.packets:
            idx = set(indices_from_seed(k, p.degree, p.seed))
            checks.append((idx, bytearray(p.payload)))

        progress = True
        while progress:
            progress = False
            for i, (idx, val) in enumerate(checks):
                if not idx:
                    continue
                unk = [u for u in idx if u not in known]
                if len(unk) != 1:
                    continue
                u = unk[0]
                res = bytearray(val)
                for j in idx:
                    if j != u and j in known:
                        for t in range(sym):
                            res[t] ^= known[j][t]
                known[u] = res
                checks[i] = (set(), bytearray())
                progress = True
        if len(known) == k:
            return b"".join(bytes(known[i]) for i in range(k))
        return None

    def _ge_bit_decode(self) -> Optional[bytes]:
        k, sym = self.k, self.symbol_size
        nvar = k * sym * 8
        rows: List[np.ndarray] = []
        rhs: List[int] = []
        for p in self.packets:
            idx = indices_from_seed(k, p.degree, p.seed)
            for bo in range(sym):
                for bit in range(8):
                    row = np.zeros(nvar, dtype=np.uint8)
                    col = bo * 8 + bit
                    for si in idx:
                        row[si * sym * 8 + col] = 1
                    bit_val = (p.payload[bo] >> (7 - bit)) & 1
                    rows.append(row)
                    rhs.append(bit_val)
        if len(rows) < nvar:
            return None
        A = np.array(rows[: nvar + 64], dtype=np.uint8)
        b = np.array(rhs[: A.shape[0]], dtype=np.uint8)
        x = _gf2_solve(A, b, nvar)
        if x is None:
            return None
        out = bytearray(k * sym)
        for si in range(k):
            for bo in range(sym):
                byte = 0
                for bit in range(8):
                    if x[si * sym * 8 + bo * 8 + bit]:
                        byte |= 1 << (7 - bit)
                out[si * sym + bo] = byte
        return bytes(out)


def _gf2_solve(A: np.ndarray, b: np.ndarray, nvar: int) -> Optional[np.ndarray]:
    m, n = A.shape
    aug = np.hstack([A.copy(), b.reshape(-1, 1)]).astype(np.uint8)
    row = 0
    pivots: List[int] = []
    for col in range(nvar):
        if row >= m:
            break
        sel = None
        for r in range(row, m):
            if aug[r, col]:
                sel = r
                break
        if sel is None:
            continue
        if sel != row:
            aug[[row, sel]] = aug[[sel, row]]
        for r in range(m):
            if r != row and aug[r, col]:
                aug[r] ^= aug[row]
        pivots.append(col)
        row += 1
    x = np.zeros(nvar, dtype=np.uint8)
    for r in range(min(row, nvar)):
        col = pivots[r] if r < len(pivots) else -1
        if col < 0:
            continue
        x[col] = aug[r, nvar]
    if np.any(aug[row:, nvar] & (np.sum(aug[row:, :nvar], axis=1) == 0)):
        return None
    if np.sum(x) == 0 and np.sum(b) > 0 and row < nvar:
        pass
    return x if row >= nvar else None


def split_message(message: bytes, symbol_size: int) -> List[bytes]:
    pad = (-len(message)) % symbol_size
    message = message + b"\x00" * pad
    return [message[i : i + symbol_size] for i in range(0, len(message), symbol_size)]
