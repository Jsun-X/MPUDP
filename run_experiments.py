#!/usr/bin/env python3
"""生成文档用实验结果图（不依赖网络）。"""

from __future__ import annotations

import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from lt_fountain import LTEncoder, LTDecoder, split_message


def _setup_chinese_font() -> None:
    """优先使用系统已安装的中文字体，避免图例/标题乱码或方框。"""
    candidates = [
        "Noto Sans CJK SC",
        "Noto Sans CJK TC",
        "Noto Sans CJK JP",
        "Noto Sans CJK KR",
        "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei",
        "Source Han Sans SC",
        "SimHei",
        "Microsoft YaHei",
        "AR PL UMing CN",
    ]
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            break
    else:
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

FIG_DIR = Path(__file__).resolve().parent / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

MESSAGE = b"MPUDP: multi-socket multipath UDP with fountain codes -- experiment payload."
SYMBOL_SIZE = 16
TRIALS = 25
SEED0 = 2025


def simulate_lt_packets_to_decode(loss: float, max_send: int = 400) -> float:
    syms = split_message(MESSAGE, SYMBOL_SIZE)
    k = len(syms)
    counts = []
    for t in range(TRIALS):
        enc = LTEncoder(syms, seed=SEED0 + t)
        stream = [enc.next_packet() for _ in range(max_send)]
        rng = random.Random(SEED0 + t + 999)
        rng.shuffle(stream)
        kept = [p for p in stream if rng.random() > loss]
        dec = LTDecoder(k, SYMBOL_SIZE)
        n = 0
        for p in kept:
            dec.add(p)
            n += 1
            if dec.try_decode() is not None:
                counts.append(n)
                break
        else:
            counts.append(float("nan"))
    arr = np.array(counts, dtype=float)
    return float(np.nanmean(arr))


def fig_packets_vs_loss():
    losses = np.linspace(0, 0.35, 8)
    means = [simulate_lt_packets_to_decode(float(l)) for l in losses]
    k = len(split_message(MESSAGE, SYMBOL_SIZE))
    plt.figure(figsize=(7, 4.5))
    plt.plot(losses * 100, means, "o-", label="LT 解码所需包数（均值）")
    plt.axhline(k, color="gray", linestyle="--", label=f"源符号数 K={k}")
    plt.xlabel("模拟丢包率 (%)")
    plt.ylabel("收到包数（首次解码成功，均值）")
    plt.title("图3  LT 喷泉码：丢包率与解码所需冗余")
    plt.grid(True, alpha=0.3)
    plt.legend()
    out = FIG_DIR / "fig3_lt_loss_vs_packets.png"
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()
    return out


def fig_overhead_success():
    syms = split_message(MESSAGE, SYMBOL_SIZE)
    k = len(syms)
    overheads = np.linspace(1.0, 2.5, 10)
    loss = 0.15
    rates = []
    for oh in overheads:
        max_send = int(k * oh)
        ok = 0
        for t in range(TRIALS):
            enc = LTEncoder(syms, seed=SEED0 + t)
            stream = [enc.next_packet() for _ in range(max_send)]
            rng = random.Random(t)
            rng.shuffle(stream)
            kept = [p for p in stream if rng.random() > loss]
            dec = LTDecoder(k, SYMBOL_SIZE)
            for p in kept:
                dec.add(p)
                if dec.try_decode() is not None:
                    ok += 1
                    break
        rates.append(ok / TRIALS * 100)
    plt.figure(figsize=(7, 4.5))
    plt.plot(overheads, rates, "s-", color="#c0392b")
    plt.xlabel("编码冗余（发送包数 / K）")
    plt.ylabel("解码成功率 (%)")
    plt.title(f"图4  固定丢包率 {loss*100:.0f}% 下 LT 冗余与成功率")
    plt.grid(True, alpha=0.3)
    plt.ylim(0, 105)
    out = FIG_DIR / "fig4_lt_overhead_vs_success.png"
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()
    return out


def main():
    _setup_chinese_font()
    p1 = fig_packets_vs_loss()
    p2 = fig_overhead_success()
    print("已写入:", p1, p2)


if __name__ == "__main__":
    main()
