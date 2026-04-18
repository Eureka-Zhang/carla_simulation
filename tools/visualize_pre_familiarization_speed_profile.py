#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pre-familiarization experiment speed curve visualization.

Timeline (与 pre_familiarization_experiment.py 当前逻辑一致):
  Phase 1 (Following):
    [pre_start_pause_s   speed=0]
    [phase_duration_s    following_irregular (slow+fast blend)]

  Phase 2 (Overtaking)（单组，速度 = --overtake-speed-kmh）:
    [overtake_cooldown_s speed=0]
    [overtake_max_duration_s   smooth ramp to target then hold]
"""

import argparse
import numpy as np
import matplotlib.pyplot as plt
import math


# 与 LeadVehicleController / pre_familiarization_experiment.py 对齐
MAX_SPEED_MS = 28.0
OVERTAKING_RAMP_TIME_S = 16.0
FOLLOWING_RAMP_TIME_S = 18.0


def kmh_to_ms(value: float) -> float:
    return value / 3.6


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _smoothstep01(x: float) -> float:
    x = _clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def following_irregular_target_speed_ms(t_s: float, center_ms: float, amp_ms: float) -> float:
    """Irregular sinusoid: slow + fast sine blended by slowly-varying blend factor."""
    slow_period_s = 95.0
    fast_period_s = 26.0
    blend_period_s = 120.0

    slow = math.sin(2.0 * math.pi * (t_s / slow_period_s))
    fast = math.sin(2.0 * math.pi * (t_s / fast_period_s))
    blend = 0.5 * (1.0 + math.sin(2.0 * math.pi * (t_s / blend_period_s)))  # in [0,1]
    wave = (1.0 - blend) * slow + blend * fast

    ramp = _smoothstep01(t_s / FOLLOWING_RAMP_TIME_S)
    return (float(center_ms) + float(amp_ms) * float(wave)) * ramp


def overtaking_target_speed(elapsed_s: float, base_speed_ms: float) -> float:
    """Overtaking lead speed: smoothstep ramp to base_speed_ms over 16s, then constant."""
    t = max(0.0, float(elapsed_s))
    if t >= OVERTAKING_RAMP_TIME_S:
        return float(base_speed_ms)

    x = t / OVERTAKING_RAMP_TIME_S
    s = x * x * (3.0 - 2.0 * x)
    return float(base_speed_ms * s)


def main():
    ap = argparse.ArgumentParser(description="Pre-familiarization speed curve")
    ap.add_argument("--phase-duration-s", type=float, default=150.0,
                    help="Following phase duration (sec), 与脚本 --phase-duration-s 对齐")
    ap.add_argument("--pre-start-pause-s", type=float, default=10.0,
                    help="Pre-start pause for following phase (sec)")
    ap.add_argument("--follow-speed-kmh", type=float, default=65.0,
                    help="Following reference center speed (km/h)")
    ap.add_argument("--follow-amp-kmh", type=float, default=15.0,
                    help="Following irregular amplitude (km/h)")
    ap.add_argument("--overtake-speed-kmh", type=float, default=50.0,
                    help="Overtaking lead target speed (km/h)")
    ap.add_argument("--overtake-cooldown-s", type=float, default=10.0,
                    help="Cooldown between following and overtaking (sec)")
    ap.add_argument("--overtake-max-duration-s", type=float, default=120.0,
                    help="Overtaking phase duration after cooldown (sec)")
    ap.add_argument("--dt", type=float, default=0.5, help="Sampling dt (sec)")
    ap.add_argument("--out", default="tools/pre_familiarization_speed_curve.png",
                    help="Output png path")
    args = ap.parse_args()

    phase_s = float(args.phase_duration_s)
    pause_s = float(args.pre_start_pause_s)
    dt = float(args.dt)
    follow_base_ms = kmh_to_ms(float(args.follow_speed_kmh))
    follow_amp_ms = kmh_to_ms(float(args.follow_amp_kmh))

    overtake_target_ms = kmh_to_ms(float(args.overtake_speed_kmh))
    cool_s = float(args.overtake_cooldown_s)
    ot_s = float(args.overtake_max_duration_s)

    # Full timeline:
    #   [Phase1 pre-pause][Phase1 following][Phase2 cooldown][Phase2 overtaking]
    total_s = pause_s + phase_s + cool_s + ot_s
    t_all = np.arange(0.0, total_s + 1e-9, dt)
    v_all = np.zeros_like(t_all)

    p1_pause_end = pause_s
    p1_end = pause_s + phase_s
    p2_cool_end = p1_end + cool_s
    p2_end = p2_cool_end + ot_s

    for i, t in enumerate(t_all):
        if t < p1_pause_end:
            # Following phase pre-pause
            v_all[i] = 0.0
        elif t < p1_end:
            # Following phase active: irregular sinusoid
            local_t = t - p1_pause_end
            v_all[i] = following_irregular_target_speed_ms(
                local_t, center_ms=follow_base_ms, amp_ms=follow_amp_ms
            ) * 3.6
        elif t < p2_cool_end:
            # Overtaking cooldown: lead held at 0
            v_all[i] = 0.0
        elif t <= p2_end:
            # Overtaking phase: smoothstep ramp to target then hold
            local_t = t - p2_cool_end
            v_all[i] = overtaking_target_speed(local_t, base_speed_ms=overtake_target_ms) * 3.6
        else:
            v_all[i] = 0.0

    plt.figure(figsize=(14, 5.5))
    plt.plot(t_all, v_all, linewidth=2.3, label="Lead target speed")
    plt.axvline(p1_pause_end, color="gray", linestyle="--", linewidth=1.2, label="Phase1 start")
    plt.axvline(p1_end, color="gray", linestyle="--", linewidth=1.2, label="Phase1 end")
    plt.axvline(p2_cool_end, color="gray", linestyle="--", linewidth=1.2, label="Phase2 start")
    plt.axvline(p2_end, color="gray", linestyle="--", linewidth=1.2, label="Phase2 end")

    plt.xlim(0, total_s)
    y_top = max(95.0, args.follow_speed_kmh + args.follow_amp_kmh + 10.0,
                float(args.overtake_speed_kmh) + 10.0)
    plt.ylim(0, y_top)
    plt.grid(True, alpha=0.3)
    plt.xlabel("Time (s)")
    plt.ylabel("Lead speed (km/h)")
    plt.title(
        "Pre-familiarization Lead Speed Plan (irregular following + single overtaking)\n"
        f"pre_pause={pause_s:.0f}s, follow={phase_s:.0f}s @ {args.follow_speed_kmh:.0f}±{args.follow_amp_kmh:.0f} km/h, "
        f"overtake_cooldown={cool_s:.0f}s, overtake={ot_s:.0f}s @ {args.overtake_speed_kmh:.0f} km/h"
    )
    plt.legend(loc="lower right", fontsize=9)
    plt.tight_layout()

    out_path = args.out
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved figure: {out_path}")
    plt.show()


if __name__ == "__main__":
    main()
