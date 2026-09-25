"""GF(2) 上 K 维源向量的线性喷泉码（工程实验用，非 RaptorQ）。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class EncodedPacket:
    """一个编码包：系数向量 c ∈ {0,1}^K，标量 y = c·s（在实数上计算，s 为小整数）。"""

    coeffs: Tuple[int, ...]
    y: float

    def to_dict(self) -> dict:
        return {"coeffs": list(self.coeffs), "y": self.y}

    @classmethod
    def from_dict(cls, d: dict) -> "EncodedPacket":
        coeffs = tuple(int(x) for x in d["coeffs"])
        return cls(coeffs=coeffs, y=float(d["y"]))


def random_encoded_packet(source_dim: int, source: Sequence[float], rng: random.Random) -> EncodedPacket:
    coeffs = tuple(rng.randint(0, 1) for _ in range(source_dim))
    if sum(coeffs) == 0:
        coeffs = tuple(1 if i == rng.randrange(source_dim) else 0 for i in range(source_dim))
    y = float(sum(c * s for c, s in zip(coeffs, source)))
    return EncodedPacket(coeffs=coeffs, y=y)


def decode_from_packets(
    packets: Iterable[EncodedPacket],
    k: int,
) -> Optional[np.ndarray]:
    """收集至少 k 个包，若存在 k 行满秩系数矩阵则解出源向量。"""
    rows: List[List[int]] = []
    ys: List[float] = []
    for pkt in packets:
        if len(pkt.coeffs) != k:
            continue
        rows.append(list(pkt.coeffs))
        ys.append(pkt.y)
    if len(rows) < k:
        return None
    A = np.array(rows, dtype=float)
    b = np.array(ys, dtype=float)
    idx = _pick_independent_rows(A, k)
    if idx is None:
        return None
    try:
        return np.linalg.solve(A[idx], b[idx])
    except np.linalg.LinAlgError:
        return None


def _pick_independent_rows(A: np.ndarray, k: int) -> Optional[List[int]]:
    """从行集中选出 k 个线性无关行的下标。"""
    n = A.shape[0]
    chosen: List[int] = []
    for i in range(n):
        trial = chosen + [i]
        if len(trial) > k:
            trial = trial[-k:]
        if np.linalg.matrix_rank(A[trial]) == min(len(trial), k):
            chosen = trial
        if len(chosen) >= k and np.linalg.matrix_rank(A[chosen[:k]]) == k:
            return chosen[:k]
    if len(chosen) >= k and np.linalg.matrix_rank(A[chosen[:k]]) == k:
        return chosen[:k]
    return None
