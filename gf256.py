"""GF(2^8) 算术，不可约多项式 x^8+x^4+x^3+x+1 (0x11B)，与 AES/RaptorQ 一致。"""

from __future__ import annotations

POLY = 0x11B


def _build_tables():
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= POLY
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


EXP, LOG = _build_tables()


def add(a: int, b: int) -> int:
    return (a ^ b) & 0xFF


def mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return EXP[LOG[a] + LOG[b]]


def div(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError
    if a == 0:
        return 0
    return EXP[(LOG[a] - LOG[b]) % 255]


def inv(a: int) -> int:
    if a == 0:
        raise ZeroDivisionError
    return EXP[255 - LOG[a]]
