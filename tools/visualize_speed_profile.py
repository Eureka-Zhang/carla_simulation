#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Visualize speed profiles for six experiments.

This script shows:
1) Lead vehicle speed profile
"""

import matplotlib.pyplot as plt
import numpy as np

OVERTAKING_SPEEDS_KMH = [35.0, 50.0, 65.0]
EXPERIMENT_DURATION_S = 200.0

# Keep these constants aligned with LeadVehicleController in car_following_experiment.py
MAX_SPEED_MS = 28.0
SMOOTH_FREQ_HZ = 1.0 / 70.0
AGGRESSIVE_FREQ_HZ = 1.0 / 28.0
OVERTAKING_RAMP_TIME_S = 16.0
FOLLOWING_BASE_SPEED_MS = 65.0 / 3.6  # 跟驰中心速度 (km/h → m/s)，与 car_following_experiment 一致
FOLLOWING_AMPLITUDE_MS = 15.0 / 3.6  # 跟驰幅值 (km/h)
FOLLOWING_STARTUP_RAMP_S = 18.0


def kmh_to_ms(value):
    return value / 3.6


def ms_to_kmh(value):
    return value * 3.6


def following_target_speed(exp_type, elapsed):
    t = max(0.0, float(elapsed))
    base = FOLLOWING_BASE_SPEED_MS
    amp = FOLLOWING_AMPLITUDE_MS

    # Match car_following_experiment.py: smooth startup from 0 to base speed.
    if t < FOLLOWING_STARTUP_RAMP_S:
        x = t / FOLLOWING_STARTUP_RAMP_S
        s = x * x * (3.0 - 2.0 * x)  # smoothstep
        return base * s

    t_wave = t - FOLLOWING_STARTUP_RAMP_S

    if exp_type == "following_aggressive":
        wave = np.sin(2.0 * np.pi * AGGRESSIVE_FREQ_HZ * t_wave)
        target = base + amp * wave
    elif exp_type == "following_irregular":
        slow_wave = np.sin(2.0 * np.pi * (1.0 / 95.0) * t_wave)
        fast_wave = np.sin(2.0 * np.pi * (1.0 / 26.0) * t_wave + 0.8)
        blend = 0.5 * (1.0 + np.sin(2.0 * np.pi * (1.0 / 120.0) * t_wave - np.pi / 2.0))
        wave = (1.0 - blend) * slow_wave + blend * fast_wave
        target = base + amp * wave
    else:
        wave = np.sin(2.0 * np.pi * SMOOTH_FREQ_HZ * t_wave)
        target = base + amp * wave

    return max(0.0, min(MAX_SPEED_MS, target))


def build_following_profile(exp_type, duration=EXPERIMENT_DURATION_S, dt=0.5):
    times = np.arange(0.0, duration + dt, dt)
    return [(float(t), float(following_target_speed(exp_type, t))) for t in times]


def build_overtaking_profile(speed_kmh):
    target_ms = kmh_to_ms(speed_kmh)
    sample_t = np.arange(0.0, EXPERIMENT_DURATION_S + 0.5, 0.5)
    profile = []
    for t in sample_t:
        if t >= OVERTAKING_RAMP_TIME_S:
            v = target_ms
        else:
            x = t / OVERTAKING_RAMP_TIME_S
            s = x * x * (3.0 - 2.0 * x)  # smoothstep
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
    fig, axes = plt.subplots(2, 3, figsize=(16, 8), sharex=True, sharey=True)

    following_defs = [
        ("Exp 1: Following smooth sinusoid", "following_smooth"),
        ("Exp 2: Following aggressive sinusoid", "following_aggressive"),
        ("Exp 3: Following variable-frequency sinusoid", "following_irregular"),
    ]
    for i, (title, exp_type) in enumerate(following_defs):
        profile = build_following_profile(exp_type)
        _plot_single(axes[0, i], profile, title)

    for i, speed_kmh in enumerate(OVERTAKING_SPEEDS_KMH):
        profile = build_overtaking_profile(speed_kmh)
        title = f"Exp {i + 4}: Overtaking {speed_kmh:.0f} km/h"
        _plot_single(axes[1, i], profile, title)

    for ax in axes[1, :]:
        ax.set_xlabel("Time (s)")

    axes[0, 0].set_ylim(0, 95)
    fig.suptitle("Six-Experiment Speed Plan: 3 Following Styles + 3 Overtaking Speeds", fontsize=14)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig("speed_profile_6_experiments.png", dpi=150, bbox_inches="tight")
    print("Saved figure: speed_profile_6_experiments.png")
    plt.show()

    print("\n=== Experiment Definitions ===")
    print("Exp 1: Following smooth sinusoid around 65 +/- 15 km/h")
    print("Exp 2: Following aggressive sinusoid around 65 +/- 15 km/h")
    print("Exp 3: Following variable-frequency sinusoid around 65 +/- 15 km/h")
    for i, speed_kmh in enumerate(OVERTAKING_SPEEDS_KMH, start=4):
        print(f"Exp {i}: Overtaking, lead starts from 0 then reaches {speed_kmh:.0f} km/h")


if __name__ == "__main__":
    plot_speed_profile()
