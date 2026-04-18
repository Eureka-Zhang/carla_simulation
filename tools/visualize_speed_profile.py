#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Visualize speed profiles for the 4-experiment plan used by car_following_experiment.py.

This script shows:
1) Following (irregular sinusoid) speed profile -- 180s
2) Overtaking profiles for 3 target speeds     -- 120s each
"""

import matplotlib.pyplot as plt
import numpy as np

# 与 car_following_experiment.py 对齐
OVERTAKING_SPEEDS_KMH = (35.0, 50.0, 65.0)
FOLLOWING_DURATION_S = 180.0
OVERTAKING_DURATION_S = 120.0

# 与 LeadVehicleController 常量对齐
MAX_SPEED_MS = 28.0
OVERTAKING_RAMP_TIME_S = 16.0
FOLLOWING_BASE_SPEED_MS = 65.0 / 3.6   # 跟驰中心速度 (km/h → m/s)
FOLLOWING_AMPLITUDE_MS = 15.0 / 3.6    # 跟驰幅值 (km/h → m/s)
FOLLOWING_STARTUP_RAMP_S = 18.0


def kmh_to_ms(value):
    return value / 3.6


def ms_to_kmh(value):
    return value * 3.6


def following_irregular_target_speed(elapsed):
    """跟驰实验（following_irregular）：启动 ramp 后使用慢+快正弦波混合。"""
    t = max(0.0, float(elapsed))
    base = FOLLOWING_BASE_SPEED_MS
    amp = FOLLOWING_AMPLITUDE_MS

    # 0 → base 的 smoothstep 启动段，避免瞬时阶跃
    if t < FOLLOWING_STARTUP_RAMP_S:
        x = t / FOLLOWING_STARTUP_RAMP_S
        s = x * x * (3.0 - 2.0 * x)
        return base * s

    t_wave = t - FOLLOWING_STARTUP_RAMP_S
    slow_wave = np.sin(2.0 * np.pi * (1.0 / 95.0) * t_wave)
    fast_wave = np.sin(2.0 * np.pi * (1.0 / 26.0) * t_wave + 0.8)
    blend = 0.5 * (1.0 + np.sin(2.0 * np.pi * (1.0 / 120.0) * t_wave - np.pi / 2.0))
    wave = (1.0 - blend) * slow_wave + blend * fast_wave
    target = base + amp * wave
    return max(0.0, min(MAX_SPEED_MS, target))


def build_following_profile(duration=FOLLOWING_DURATION_S, dt=0.5):
    times = np.arange(0.0, duration + dt, dt)
    return [(float(t), float(following_irregular_target_speed(t))) for t in times]


def build_overtaking_profile(speed_kmh, duration=OVERTAKING_DURATION_S, dt=0.5):
    target_ms = kmh_to_ms(speed_kmh)
    sample_t = np.arange(0.0, duration + dt, dt)
    profile = []
    for t in sample_t:
        if t >= OVERTAKING_RAMP_TIME_S:
            v = target_ms
        else:
            x = t / OVERTAKING_RAMP_TIME_S
            s = x * x * (3.0 - 2.0 * x)
            v = target_ms * s
        profile.append((float(t), float(v)))
    return profile


def _plot_single(ax, lead_profile, title):
    lead_times = [p[0] for p in lead_profile]
    lead_speed_ms = [p[1] for p in lead_profile]
    t_interp = np.linspace(lead_times[0], lead_times[-1], 600)
    lead_interp_kmh = np.interp(t_interp, lead_times, lead_speed_ms) * 3.6

    ax.plot(t_interp, lead_interp_kmh, linewidth=2.2, color="#1f77b4", label="Lead speed")

    ax.grid(True, alpha=0.3)
    ax.set_title(title, fontsize=11)
    ax.set_ylabel("Speed (km/h)")
    ax.legend(loc="lower right", fontsize=8)


def plot_speed_profile():
    # 4 组实验：1 跟驰 + 3 超车，采用 2x2 布局
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))

    # Exp 1: Following (irregular)
    _plot_single(
        axes[0, 0],
        build_following_profile(),
        f"Exp 1: Following irregular (0~{int(FOLLOWING_DURATION_S)}s)",
    )

    # Exp 2/3/4: Overtaking at 3 target speeds
    for i, speed_kmh in enumerate(OVERTAKING_SPEEDS_KMH):
        row = (i + 1) // 2
        col = (i + 1) % 2
        ax = axes[row, col]
        _plot_single(
            ax,
            build_overtaking_profile(speed_kmh),
            f"Exp {i + 2}: Overtaking {speed_kmh:.0f} km/h (0~{int(OVERTAKING_DURATION_S)}s)",
        )

    # x 轴标签只在底部一行显示
    for ax in axes[-1, :]:
        ax.set_xlabel("Time (s)")

    # y 轴上限统一：跟驰最高约 80 km/h，超车最高 65 km/h → 留一些富余
    for ax_row in axes:
        for ax in ax_row:
            ax.set_ylim(0, 95)

    fig.suptitle("Four-Experiment Speed Plan: 1 Following Irregular + 3 Overtaking Speeds", fontsize=14)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    out_path = "speed_profile_4_experiments.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved figure: {out_path}")
    plt.show()

    print("\n=== Experiment Definitions ===")
    print(f"Exp 1: Following irregular sinusoid around 65 +/- 15 km/h (duration {FOLLOWING_DURATION_S:.0f}s)")
    for i, speed_kmh in enumerate(OVERTAKING_SPEEDS_KMH, start=2):
        print(
            f"Exp {i}: Overtaking, lead ramps from 0 to {speed_kmh:.0f} km/h "
            f"over {OVERTAKING_RAMP_TIME_S:.0f}s then holds (total {OVERTAKING_DURATION_S:.0f}s)"
        )


if __name__ == "__main__":
    plot_speed_profile()
