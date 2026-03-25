#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pre-familiarization experiment speed curve visualization.

Timeline:
  Phase 1 (Following): irregular sinusoid (slow+fast blend) after pre-start pause
  Phase 2 (Overtaking): grouped segments with cooldown between groups
                        (smooth ramp to constant each segment), after pre-start pause
"""

import argparse
import numpy as np
import matplotlib.pyplot as plt
import math

# Keep these constants aligned with LeadVehicleController in car_following_experiment.py
MAX_SPEED_MS = 28.0
MIN_SPEED_MS = 12.0
MAX_ACCELERATION = 2.0
MAX_DECELERATION = 3.0
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
    """
    Irregular sinusoid used by pre_familiarization_experiment.py:
    slow + fast sine blended by a slowly-varying blend factor.
    """
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
    ap.add_argument("--phase-duration-s", type=float, default=150.0, help="Following phase duration (sec)")
    ap.add_argument("--pre-start-pause-s", type=float, default=15.0, help="Pre-start pause each phase (sec)")
    ap.add_argument("--follow-speed-kmh", type=float, default=65.0, help="Following reference speed (km/h)")
    ap.add_argument("--follow-amp-kmh", type=float, default=15.0, help="Following irregular amplitude (km/h)")
    ap.add_argument("--overtake-segment-duration-s", type=float, default=60.0, help="Overtaking per-group driving duration (sec)")
    ap.add_argument("--overtake-cooldown-s", type=float, default=5.0, help="Cooldown between overtaking groups (sec)")
    ap.add_argument("--overtake-speeds-kmh", type=str, default="35,50,65,75", help="Overtaking speeds list (km/h)")
    ap.add_argument("--dt", type=float, default=0.5, help="Sampling dt (sec)")
    ap.add_argument("--out", default="tools/pre_familiarization_speed_curve.png", help="Output png path")
    args = ap.parse_args()

    phase_s = float(args.phase_duration_s)
    pause_s = float(args.pre_start_pause_s)
    dt = float(args.dt)
    follow_base_ms = kmh_to_ms(float(args.follow_speed_kmh))
    follow_amp_ms = kmh_to_ms(float(args.follow_amp_kmh))

    # Parse overtake speeds list
    try:
        overtake_speeds = [float(x.strip()) for x in str(args.overtake_speeds_kmh).split(",") if x.strip()]
    except Exception:
        overtake_speeds = [35.0, 50.0, 65.0, 75.0]
    if not overtake_speeds:
        overtake_speeds = [35.0, 50.0, 65.0, 75.0]

    seg_s = float(args.overtake_segment_duration_s)
    cool_s = float(args.overtake_cooldown_s)
    n = len(overtake_speeds)
    overtake_total_s = n * seg_s + max(0, n - 1) * cool_s

    # Full timeline includes pauses:
    # [Phase1 pause][Phase1 active][Phase2 pause][Phase2 active]
    total_s = (pause_s + phase_s) + (pause_s + overtake_total_s)
    t_all = np.arange(0.0, total_s + 1e-9, dt)
    v_all = np.zeros_like(t_all)

    # Phase boundaries
    p1_pause_end = pause_s
    p1_end = pause_s + phase_s
    p2_pause_end = p1_end + pause_s
    p2_end = p2_pause_end + overtake_total_s

    # Phase 1 (following) irregular sinusoid during active window
    for i, t in enumerate(t_all):
        if t < p1_pause_end:
            v_all[i] = 0.0
        elif t < p1_end:
            local_t = t - p1_pause_end
            v_all[i] = following_irregular_target_speed_ms(local_t, center_ms=follow_base_ms, amp_ms=follow_amp_ms) * 3.6
        elif t < p2_pause_end:
            v_all[i] = 0.0
        elif t <= p2_end:
            # Phase 2 (overtaking) grouped segments with cooldown
            local_t = t - p2_pause_end
            # walk over groups
            t_rem = float(local_t)
            speed_kmh = float(overtake_speeds[-1])
            in_cooldown = False
            seg_t = 0.0
            for k in range(n):
                if t_rem < seg_s:
                    speed_kmh = float(overtake_speeds[k])
                    in_cooldown = False
                    seg_t = float(t_rem)
                    break
                t_rem -= seg_s
                if k == n - 1:
                    speed_kmh = float(overtake_speeds[k])
                    in_cooldown = False
                    seg_t = float(seg_s)
                    break
                if t_rem < cool_s:
                    speed_kmh = float(overtake_speeds[k + 1])  # next group info (for label only)
                    in_cooldown = True
                    seg_t = 0.0
                    break
                t_rem -= cool_s

            if in_cooldown:
                v_all[i] = 0.0
            else:
                v_all[i] = overtaking_target_speed(seg_t, base_speed_ms=kmh_to_ms(speed_kmh)) * 3.6
        else:
            v_all[i] = 0.0

    plt.figure(figsize=(14, 5.5))
    plt.plot(t_all, v_all, linewidth=2.3, label="Lead target speed")
    plt.axvline(p1_pause_end, color="gray", linestyle="--", linewidth=1.2, label="Phase1 start")
    plt.axvline(p1_end, color="gray", linestyle="--", linewidth=1.2, label="Phase1 end")
    plt.axvline(p2_pause_end, color="gray", linestyle="--", linewidth=1.2, label="Phase2 start")
    plt.axvline(p2_end, color="gray", linestyle="--", linewidth=1.2, label="Phase2 end")

    plt.xlim(0, total_s)
    plt.ylim(0, 100)
    plt.grid(True, alpha=0.3)
    plt.xlabel("Time (s)")
    plt.ylabel("Lead speed (km/h)")
    plt.title(
        "Pre-familiarization Lead Speed Plan (irregular following + grouped overtaking)\n"
        f"pause={pause_s:.0f}s, follow={phase_s:.0f}s, overtake_total={overtake_total_s:.0f}s "
        f"(seg={seg_s:.0f}s, cooldown={cool_s:.0f}s), overtake_speeds={','.join([str(int(x)) for x in overtake_speeds])}"
    )
    plt.legend(loc="lower right", fontsize=9)
    plt.tight_layout()

    out_path = args.out
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved figure: {out_path}")
    plt.show()


if __name__ == "__main__":
    main()

