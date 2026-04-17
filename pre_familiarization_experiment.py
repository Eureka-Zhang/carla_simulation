#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
前置熟悉实验（默认采集数据）

两个阶段合计 5min（每阶段 2.5min）：
1) 跟驰：在大屏显示“请进行跟驰”
2) 超车：在大屏显示“请进行超车”

阶段切换时重置前车控制器，并可选重置前车/自车速度到 0（便于被试起步）。
"""

import argparse
import os
import time
import math
from datetime import datetime
from typing import Optional

import pygame
import carla

import car_following_experiment as cfe


def kmh_to_ms(kmh: float) -> float:
    return kmh / 3.6


def fmt_mm_ss(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    mm = int(seconds // 60)
    ss = int(seconds % 60)
    return f"{mm:02d}:{ss:02d}"


def draw_big_message(display, font_large, text: str, remaining_s: float, width: int, height: int):
    """居中显示提示词与倒计时，统一字号与颜色。"""
    color = (255, 255, 255)
    shadow_color = (0, 0, 0)

    lines = []
    if text:
        lines.append(str(text))
    lines.append(f"倒计时: {fmt_mm_ss(remaining_s)}")

    surfaces = []
    for line in lines:
        surf = font_large.render(line, True, color)
        shadow = font_large.render(line, True, shadow_color)
        surfaces.append((surf, shadow))

    line_gap = 10
    total_h = sum(surf.get_height() for surf, _ in surfaces) + line_gap * max(0, len(surfaces) - 1)
    y = (height - total_h) // 2
    for surf, shadow in surfaces:
        x = (width - surf.get_width()) // 2
        display.blit(shadow, (x + 3, y + 3))
        display.blit(surf, (x, y))
        y += surf.get_height() + line_gap


class KeyboardDriver:
    """简化键盘驾驶：仅用于前置熟悉实验（可快速让被试进入状态）"""

    def __init__(self):
        self.throttle = 0.0
        self.brake = 0.0
        self.steer_cache = 0.0

    def update(self, keys, dt_ms: float, ackermann_enabled: bool = False) -> carla.VehicleControl:
        # Ackermann 模式下 steer/throttle 可能不同；这里前置实验默认不启用 Ackermann
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            self.throttle = min(1.0, self.throttle + 0.05)
        else:
            self.throttle = 0.0

        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            self.brake = min(1.0, self.brake + 0.1)
        else:
            self.brake = 0.0

        steer_increment = 5e-4 * dt_ms
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            if self.steer_cache > 0:
                self.steer_cache = 0.0
            else:
                self.steer_cache -= steer_increment
        elif keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            if self.steer_cache < 0:
                self.steer_cache = 0.0
            else:
                self.steer_cache += steer_increment
        else:
            self.steer_cache = 0.0

        self.steer_cache = min(0.7, max(-0.7, self.steer_cache))

        return carla.VehicleControl(
            throttle=self.throttle,
            steer=round(self.steer_cache, 2),
            brake=self.brake,
            hand_brake=keys[pygame.K_SPACE],
            reverse=False,
            manual_gear_shift=False,
        )


def main():
    argparser = argparse.ArgumentParser(description="前置熟悉实验（跟驰/超车）")

    # CARLA 连接
    argparser.add_argument("--host", default="127.0.0.1", help="CARLA 服务器 IP")
    argparser.add_argument("-p", "--port", default=2000, type=int, help="CARLA 服务器端口")

    # 显示设置
    argparser.add_argument("--res", default="1920x1080", help="窗口分辨率，例如 1920x1080")
    argparser.add_argument("--display", default=0, type=int, help="显示器编号（用于大屏展示）")
    argparser.add_argument("--fullscreen", action="store_true", help="全屏模式")
    argparser.add_argument("--gamma", default=2.2, type=float, help="Gamma 校正（与主脚本一致）")

    # 车辆设置
    argparser.add_argument("--filter", default="vehicle.audi.tt", help="自车蓝图过滤")
    argparser.add_argument("--generation", default="2", help="车辆代次")
    argparser.add_argument("--rolename", default="hero", help="自车角色名")
    argparser.add_argument("--lead-vehicle", default="vehicle.tesla.model3", help="前车蓝图")
    argparser.add_argument("--lead-distance", default=50.0, type=float, help="前车初始距离（米）")

    # 控制模式
    argparser.add_argument("--keyboard", action="store_true", help="使用键盘控制自车")
    argparser.add_argument("--cabin", action="store_true", help="使用驾驶舱控制自车（需要 UDP）")
    argparser.add_argument("--cabin-ip", default=cfe.CABIN_IP, help="驾驶舱 IP")
    argparser.add_argument("--cabin-port", default=cfe.CABIN_PORT, type=int, help="驾驶舱端口")
    argparser.add_argument(
        "--cabin-echo-interval",
        default=None,
        type=float,
        metavar="N",
        help="驾驶舱回传打印间隔（秒），例如 0.25；0=关闭。默认 cabin=0.25、keyboard=0",
    )

    # 地图/同步设置
    argparser.add_argument("--sync", action="store_true", default=True, help="启用同步模式")
    argparser.add_argument("--no-sync", dest="sync", action="store_false", help="禁用同步模式")
    argparser.add_argument("--map", default=None, help="CARLA 地图名（不指定则使用当前加载地图）")
    argparser.add_argument("--straight-road", action="store_true", default=False, help="使用内置直道地图（实验性）")
    argparser.add_argument("--opendrive", default=None, type=str, help="加载自定义 OpenDRIVE（.xodr）")

    # 阶段时长与速度
    argparser.add_argument("--phase-duration-s", default=150.0, type=float, help="跟驰阶段时长（秒），默认 2.5min")
    argparser.add_argument("--follow-speed-kmh", default=65.0, type=float, help="跟驰阶段中心速度（km/h）")
    argparser.add_argument("--follow-amp-kmh", default=15.0, type=float, help="跟驰阶段不规则变速幅值（km/h）")

    # 超车：4组速度，每组 30s，组间冷却 5s，总时长 135s（=4*30 + 3*5）
    argparser.add_argument("--overtake-segment-duration-s", default=30.0, type=float, help="超车每组时长（秒），默认30s")
    argparser.add_argument("--overtake-cooldown-s", default=5.0, type=float, help="超车组间冷却（秒），默认5s（冷却时前车速度为0）")
    argparser.add_argument(
        "--overtake-speeds-kmh",
        default="35,50,65,75",
        type=str,
        help="超车阶段速度列表（km/h，用逗号分隔），默认 35,50,65,75",
    )

    argparser.add_argument("--pre-start-pause-s", default=10.0, type=float, help="每阶段开始前暂停时间（秒），默认10s")

    args = argparser.parse_args()

    args.width, args.height = [int(x) for x in args.res.split("x")]
    if args.cabin:
        args.input_mode = "cabin"
    else:
        args.input_mode = "keyboard"
    if args.cabin_echo_interval is None:
        args.cabin_echo_interval = 0.25 if args.input_mode == "cabin" else 0.0

    # 主脚本 World.restart() / _get_effective_lead_speed() 依赖 args.lead_speed
    # 这里为“前车初始生成/默认基准”提供一个值；实际阶段内我们会在 reset_lead_for_phase() 再将前车速度置 0 并切换行为。
    args.lead_speed = kmh_to_ms(args.follow_speed_kmh)
    # 让 World 中 follow_road 的逻辑能兼容（主脚本使用 straight_drive 字段）
    args.straight_drive = getattr(args, "straight_road", False)

    # 只用于搭建世界，不启用 6 组实验切换
    args.enable_experiment_mode = False
    args.experiment_cooldown_s = 0.0
    args.six_experiments = False

    # ----------------- CARLA / pygame 初始化 -----------------
    pygame.init()
    pygame.font.init()

    display_flags = pygame.HWSURFACE | pygame.DOUBLEBUF
    if args.fullscreen:
        display_flags |= pygame.FULLSCREEN
    # 与主脚本保持一致：将 display_flags 作为 set_mode 的 flags 位置参数
    display = pygame.display.set_mode((args.width, args.height), display_flags, display=args.display)
    display.fill((0, 0, 0))

    client = carla.Client(args.host, args.port)
    client.set_timeout(60.0)

    # 地图加载（可选）
    sim_world = None
    if args.straight_road or args.opendrive:
        opendrive_file = None
        if args.straight_road:
            opendrive_file = os.path.join(os.path.dirname(__file__), "maps", "straight_road.xodr")
        elif args.opendrive:
            opendrive_file = args.opendrive
        if not opendrive_file or not os.path.exists(opendrive_file):
            raise FileNotFoundError(f"未找到 OpenDRIVE: {opendrive_file}")
        with open(opendrive_file, "r", encoding="utf-8") as f:
            opendrive_content = f.read()
        sim_world = client.generate_opendrive_world(
            opendrive_content,
            carla.OpendriveGenerationParameters(
                vertex_distance=2.0,
                max_road_length=500.0,
                wall_height=1.0,
                additional_width=0.6,
                smooth_junctions=True,
                enable_mesh_visibility=True,
            ),
        )
    else:
        if args.map:
            sim_world = client.load_world(args.map)
        else:
            sim_world = client.get_world()

    # 前置熟悉实验启动前：清理场景里残留车辆，避免 ego/lead 生成失败
    try:
        for actor in sim_world.get_actors().filter("vehicle.*"):
            actor.destroy()
        # 给一下服务器处理销毁的时间
        time.sleep(0.2)
    except Exception:
        pass

    original_settings = sim_world.get_settings()
    if args.sync:
        settings = sim_world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        sim_world.apply_settings(settings)

    hud = cfe.HUD(args.width, args.height)
    world = cfe.World(sim_world, hud, args)
    world.recording_enabled = False

    controller = cfe.VehicleController(world, args)
    keyboard_driver = KeyboardDriver()  # 仅 keyboard 模式使用

    # 由于我们要在大屏显示中文：复用主脚本的中文字体查找
    chinese_font = cfe.find_chinese_font()
    if chinese_font:
        font_large = pygame.font.Font(chinese_font, 64)
    else:
        font_large = pygame.font.Font(None, 64)

    # 阶段配置
    phases = [
        ("following", "请进行跟驰", "following_irregular", kmh_to_ms(args.follow_speed_kmh)),
        ("overtaking", "请进行跟驰", "overtaking_groups", 0.0),
    ]

    running = True
    phase_idx = 0
    phase_segment_idx = 0
    phase_record_started = {"following": False, "overtaking": False}

    # 解析超车速度序列（km/h）
    try:
        overtake_speeds_kmh = [float(x.strip()) for x in str(args.overtake_speeds_kmh).split(",") if x.strip()]
    except Exception:
        overtake_speeds_kmh = [35.0, 50.0, 65.0, 75.0]
    if not overtake_speeds_kmh:
        overtake_speeds_kmh = [35.0, 50.0, 65.0, 75.0]
    overtake_group_idx = 0
    overtake_in_cooldown = False
    overtake_group_start_wall = None
    overtake_phase_start_wall = None
    overtake_prompt_until_wall = 0.0
    overtake_speed_reached = False
    overtake_active_group_idx = None

    def _start_segment_recording(phase_name: str):
        """开始某一阶段的分段采集（每次调用都会产生带时间戳的新文件）。"""
        nonlocal phase_segment_idx
        if world is None or world.data_collector is None:
            return

        sim_time = world.hud.simulation_time if hasattr(world.hud, "simulation_time") else None
        if world.data_collector.is_collecting:
            saved_path = world.data_collector.stop(world_end_time_s=sim_time)
            if saved_path:
                print(f"[前置熟悉实验] 分段保存完成: {saved_path}")

        phase_segment_idx += 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        save_dir = f"./experiment_data/pre_familiarization_{ts}_seg{phase_segment_idx:03d}_{phase_name}"
        save_path = os.path.join(save_dir, "driving_data.csv")
        world.data_collector.start(
            save_path,
            world.lead_controller,
            world_start_time_s=sim_time,
        )
        if phase_name == "overtaking" and getattr(world.data_collector, "metadata", None) is not None:
            n = len(overtake_speeds_kmh)
            world.data_collector.metadata["overtaking_group_world_time"] = [
                {
                    "group_index": i + 1,
                    "target_speed_kmh": float(overtake_speeds_kmh[i]),
                    "start_world_time_s": None,
                    "end_world_time_s": None,
                }
                for i in range(n)
            ]
            world.data_collector.metadata["overtaking_group_world_time_events"] = []
            if hasattr(world.data_collector, "_write_metadata"):
                world.data_collector._write_metadata()
        hud.notification(f"分段采集开始: {phase_name}", seconds=1.8)

    def _stop_segment_recording():
        if world is None or world.data_collector is None or (not world.data_collector.is_collecting):
            return
        sim_time = world.hud.simulation_time if hasattr(world.hud, "simulation_time") else None
        saved_path = world.data_collector.stop(world_end_time_s=sim_time)
        if saved_path:
            print(f"[前置熟悉实验] 分段保存完成: {saved_path}")

    def _mark_overtake_group_world_time(group_idx: int, edge: str, sim_time: Optional[float]):
        if (
            world is None
            or world.data_collector is None
            or (not world.data_collector.is_collecting)
            or getattr(world.data_collector, "metadata", None) is None
            or group_idx < 0
            or group_idx >= len(overtake_speeds_kmh)
        ):
            return
        md = world.data_collector.metadata
        groups = md.get("overtaking_group_world_time")
        if not isinstance(groups, list) or len(groups) != len(overtake_speeds_kmh):
            return
        key = "start_world_time_s" if edge == "start" else "end_world_time_s"
        groups[group_idx][key] = float(sim_time) if sim_time is not None else None
        md.setdefault("overtaking_group_world_time_events", []).append(
            {
                "group_index": group_idx + 1,
                "edge": edge,
                "world_time_s": float(sim_time) if sim_time is not None else None,
                "wall_time": datetime.now().isoformat(timespec="milliseconds"),
            }
        )
        if hasattr(world.data_collector, "_write_metadata"):
            world.data_collector._write_metadata()

    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    def _smoothstep01(x: float) -> float:
        x = _clamp(x, 0.0, 1.0)
        return x * x * (3.0 - 2.0 * x)

    def following_irregular_target_speed_ms(t_s: float) -> float:
        """
        不规则变速（参考主脚本最后一个不规则跟驰的思路）：
        - 慢波 + 快波
        - blend 随时间缓慢变化，使快慢段交替出现但整体仍连续平滑
        """
        center_ms = kmh_to_ms(float(args.follow_speed_kmh))
        amp_ms = kmh_to_ms(float(args.follow_amp_kmh))
        slow_period_s = 95.0
        fast_period_s = 26.0
        blend_period_s = 120.0
        slow = math.sin(2.0 * math.pi * (t_s / slow_period_s))
        fast = math.sin(2.0 * math.pi * (t_s / fast_period_s))
        # blend in [0,1]
        blend = 0.5 * (1.0 + math.sin(2.0 * math.pi * (t_s / blend_period_s)))
        wave = (1.0 - blend) * slow + blend * fast
        return center_ms + amp_ms * wave

    def cleanup_other_vehicles(keep_ids):
        """清理残留车辆：保留自车/前车，其余 vehicle.* 全部销毁。"""
        try:
            for actor in world.world.get_actors().filter("vehicle.*"):
                if actor.id in keep_ids:
                    continue
                # 避免销毁刚生成的其他车辆角色名以外，简单按 id 清理
                actor.destroy()
        except Exception:
            # 清理失败不应阻断实验
            pass

    def refresh_controller_after_restart():
        """World.restart() 后刷新驾驶舱控制器引用（避免仍引用旧车体物理）。"""
        try:
            if world.player:
                controller._physics_control = world.player.get_physics_control()
        except Exception:
            pass

    def hard_restart_world():
        """重启场景并尽量保证 player 可用。"""
        # 先清理残留车辆，避免生成失败
        keep_ids = set()
        if world.player is not None:
            keep_ids.add(world.player.id)
        if world.lead_vehicle is not None:
            keep_ids.add(world.lead_vehicle.id)
        cleanup_other_vehicles(keep_ids=keep_ids)

        world.restart()
        if world.player is None:
            # 再清一次，重试一次
            try:
                for actor in world.world.get_actors().filter("vehicle.*"):
                    actor.destroy()
                time.sleep(0.2)
            except Exception:
                pass
            world.restart()
        refresh_controller_after_restart()

    # 创建/重置前车控制器
    def reset_lead_for_phase(phase_type: str, base_speed_ms: float):
        if world.lead_vehicle is None:
            return
        # 重置前车速度到 0，让阶段开始更“干净”
        world.lead_vehicle.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
        if world.player is not None:
            world.player.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
            world.player.apply_control(carla.VehicleControl(throttle=0.0, brake=0.0, steer=0.0))
        # 跟驰阶段不再用主脚本 controller（主脚本已简化为规则余弦）；这里我们自行在主循环里驱动不规则目标速度。
        if phase_type == "following_irregular":
            world.lead_controller = None
            return

        # 超车阶段（分组匀速/平滑起步）：复用主脚本 LeadVehicleController 的 overtaking 逻辑即可
        world.lead_controller = cfe.LeadVehicleController(
            world.lead_vehicle,
            base_speed=base_speed_ms,
            random_mode=False,
            random_seed=None,
            follow_road=True,
            experiment_type="overtaking",
        )
        world.lead_controller.start()

    # 初始化阶段（阶段开始前先暂停 + 清理）
    # 清理阶段开始前残留的“左边车辆”等
    keep_ids = set()
    if world.player is not None:
        keep_ids.add(world.player.id)
    if world.lead_vehicle is not None:
        keep_ids.add(world.lead_vehicle.id)
    cleanup_other_vehicles(keep_ids=keep_ids)

    phase_type, phase_text, exp_type_str, base_speed_ms = phases[phase_idx][0], phases[phase_idx][1], phases[phase_idx][2], phases[phase_idx][3]
    reset_lead_for_phase(exp_type_str, base_speed_ms)

    clock = pygame.time.Clock()

    pause_remaining_s = float(args.pre_start_pause_s)
    pause_end_wall = time.time() + pause_remaining_s
    phase_start_wall = None  # 真正实验开始时刻（暂停结束后）

    try:
        while running:
            # 同步模式：先推进 CARLA 时间
            if args.sync:
                sim_world.tick()
            else:
                sim_world.wait_for_tick()

            clock.tick_busy_loop(30)

            # 事件 + 自车控制
            # 注意：暂停期间我们会覆盖自车控制为 0，避免被试误触导致移动
            now_wall = time.time()
            phase_pause_active = now_wall < pause_end_wall

            if args.input_mode == "keyboard":
                # 仅保留退出事件；控制量用 key.get_pressed 采样
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        running = False
                if not running:
                    break

                keys = pygame.key.get_pressed()
                dt_ms = clock.get_time()
                if dt_ms <= 0:
                    dt_ms = 33
                ctrl = keyboard_driver.update(keys, dt_ms)
                applied_ctrl = ctrl
                if phase_pause_active:
                    applied_ctrl = carla.VehicleControl(throttle=0.0, brake=0.0, steer=0.0)
                    world.player.apply_control(applied_ctrl)
                else:
                    world.player.apply_control(applied_ctrl)

                # keyboard 模式未经过 controller.parse_events，需要在此手动采集数据
                if world.data_collector.is_collecting and world.player is not None and world.lead_vehicle is not None:
                    world.data_collector.collect(
                        world.player,
                        world.lead_vehicle,
                        applied_ctrl,
                        "manual",
                        world.lead_controller,
                    )
            else:
                # cabin 模式：让主脚本的 UDP 输入逻辑接管事件
                if controller.parse_events(client, world, clock, args.sync):
                    running = False
                    break

                # cabin 模式下也覆盖暂停控制为 0
                if phase_pause_active:
                    try:
                        world.player.apply_control(carla.VehicleControl(throttle=0.0, brake=0.0, steer=0.0))
                    except Exception:
                        pass

            # 更新 lead controller（暂停期间不更新，让前车保持 0）
            sim_time = world.hud.simulation_time if hasattr(world.hud, "simulation_time") else None
            current_phase_name = phases[phase_idx][0]
            # 跟驰段：阶段正式开始后即开始采集
            if (
                current_phase_name == "following"
                and (not phase_pause_active)
                and (phase_start_wall is not None)
                and (not phase_record_started["following"])
            ):
                _start_segment_recording("following")
                phase_record_started["following"] = True
            if current_phase_name == "following" and (not phase_pause_active) and (phase_start_wall is not None) and world.lead_vehicle is not None:
                # 跟驰不规则变速：用 set_target_velocity 直接驱动前车目标速度
                t = now_wall - phase_start_wall
                target_ms = following_irregular_target_speed_ms(t)
                # 起步做一个平滑 ramp（避免一开始就给大速度）
                ramp_s = 18.0
                ramp = _smoothstep01(t / ramp_s)
                target_ms *= ramp
                try:
                    tf = world.lead_vehicle.get_transform()
                    fwd = tf.get_forward_vector()
                    world.lead_vehicle.set_target_velocity(carla.Vector3D(fwd.x * target_ms, fwd.y * target_ms, 0.0))
                except Exception:
                    pass
            elif world.lead_controller and (not phase_pause_active) and sim_time is not None:
                world.lead_controller.update(sim_time)
            elif world.lead_vehicle:
                # 强制前车目标速度为0，保证被清理后仍处于静止/冷却阶段
                try:
                    world.lead_vehicle.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
                except Exception:
                    pass

            # 超车阶段：总时长135s；4组速度各30s，组间冷却5s（4*30 + 3*5）
            if current_phase_name == "overtaking" and (not phase_pause_active) and (phase_start_wall is not None):
                if overtake_phase_start_wall is None:
                    overtake_phase_start_wall = phase_start_wall
                    overtake_group_start_wall = None
                    overtake_group_idx = 0
                    overtake_in_cooldown = False

                seg_s = float(args.overtake_segment_duration_s)
                cool_s = float(args.overtake_cooldown_s)
                n = len(overtake_speeds_kmh)
                total_s = n * seg_s + max(0, n - 1) * cool_s
                elapsed_total = now_wall - overtake_phase_start_wall

                # 计算当前处于哪一段（第k组行驶 or 冷却）
                k = 0
                t = elapsed_total
                in_cooldown = False
                while k < n:
                    if t < seg_s:
                        in_cooldown = False
                        break
                    t -= seg_s
                    if k == n - 1:
                        in_cooldown = False
                        break
                    if t < cool_s:
                        in_cooldown = True
                        break
                    t -= cool_s
                    k += 1

                overtake_group_idx = k
                overtake_in_cooldown = in_cooldown

                # 超车段：仅在前车速度非零后开始采集（避免记录超车前静止段）
                if (
                    (not overtake_in_cooldown)
                    and (not phase_record_started["overtaking"])
                    and world.lead_vehicle is not None
                ):
                    lv0 = world.lead_vehicle.get_velocity()
                    lead_speed0 = math.sqrt(lv0.x * lv0.x + lv0.y * lv0.y + lv0.z * lv0.z)
                    if lead_speed0 > 0.2:
                        _start_segment_recording("overtaking")
                        phase_record_started["overtaking"] = True

                # 记录超车四段（行驶段）开始/结束世界时间
                if not overtake_in_cooldown:
                    if overtake_active_group_idx != overtake_group_idx:
                        if overtake_active_group_idx is not None:
                            _mark_overtake_group_world_time(overtake_active_group_idx, "end", sim_time)
                        overtake_active_group_idx = overtake_group_idx
                        _mark_overtake_group_world_time(overtake_active_group_idx, "start", sim_time)
                elif overtake_active_group_idx is not None:
                    _mark_overtake_group_world_time(overtake_active_group_idx, "end", sim_time)
                    overtake_active_group_idx = None

                # 在每组“行驶段”开始时重启并设置该组速度（只触发一次）
                if (not overtake_in_cooldown) and (overtake_group_start_wall is None or now_wall - overtake_group_start_wall < 0):
                    # 不会走到这里；保底
                    pass
                if (not overtake_in_cooldown):
                    # 检测是否刚进入新的行驶段：用一个阈值判断“t 接近 0”
                    if t < 0.08 and overtake_group_start_wall != overtake_group_idx:
                        hard_restart_world()
                        reset_lead_for_phase("overtaking", kmh_to_ms(overtake_speeds_kmh[overtake_group_idx]))
                        overtake_prompt_until_wall = 0.0
                        overtake_speed_reached = False
                        # 用一个小技巧：把 overtake_group_start_wall 复用成“已触发的组号”
                        overtake_group_start_wall = overtake_group_idx
                else:
                    # 冷却：强制前车速度为0，并停用 controller
                    world.lead_controller = None
                    try:
                        if world.lead_vehicle is not None:
                            world.lead_vehicle.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
                    except Exception:
                        pass
                    overtake_prompt_until_wall = 0.0
                    overtake_speed_reached = False

            # HUD 更新（不调用 World.tick，避免 lead_controller 在暂停期间被推进）
            world.hud.tick(world, clock)

            # 渲染
            world.render(display)

            # 绘制阶段大字/倒计时（覆盖在渲染之上）
            if phase_pause_active:
                remaining = pause_end_wall - now_wall
                draw_big_message(display, font_large, "暂停中", remaining, args.width, args.height)
            else:
                if phase_start_wall is None:
                    phase_start_wall = now_wall
                _, phase_text, _, _ = phases[phase_idx]
                if phases[phase_idx][0] == "overtaking":
                    # 超车阶段：显示总倒计时（135s）
                    seg_s = float(args.overtake_segment_duration_s)
                    cool_s = float(args.overtake_cooldown_s)
                    n = len(overtake_speeds_kmh)
                    total_s = n * seg_s + max(0, n - 1) * cool_s
                    if overtake_phase_start_wall is None:
                        remaining = total_s
                    else:
                        remaining = total_s - (now_wall - overtake_phase_start_wall)
                    phase_text_draw = ""
                    if overtake_in_cooldown:
                        phase_text_draw = "请进行跟驰"
                    elif 0 <= overtake_group_idx < len(overtake_speeds_kmh) and world.lead_vehicle is not None:
                        target_ms = kmh_to_ms(overtake_speeds_kmh[overtake_group_idx])
                        lv = world.lead_vehicle.get_velocity()
                        lead_speed = math.sqrt(lv.x * lv.x + lv.y * lv.y + lv.z * lv.z)
                        if (not overtake_speed_reached) and lead_speed >= max(0.0, target_ms * 0.95):
                            overtake_speed_reached = True
                            overtake_prompt_until_wall = now_wall + 1.5
                        if now_wall < overtake_prompt_until_wall:
                            phase_text_draw = "请进行超车"
                        elif not overtake_speed_reached:
                            phase_text_draw = "请进行跟驰"
                    draw_big_message(display, font_large, phase_text_draw, remaining, args.width, args.height)
                else:
                    remaining = args.phase_duration_s - (now_wall - phase_start_wall)
                    draw_big_message(display, font_large, phase_text, remaining, args.width, args.height)
            pygame.display.flip()

            # 计时与阶段切换
            should_switch = False
            if (not phase_pause_active) and phase_start_wall is not None:
                if phases[phase_idx][0] == "overtaking":
                    # 超车阶段按总时长结束（135s）
                    seg_s = float(args.overtake_segment_duration_s)
                    cool_s = float(args.overtake_cooldown_s)
                    n = len(overtake_speeds_kmh)
                    total_s = n * seg_s + max(0, n - 1) * cool_s
                    if overtake_phase_start_wall is not None and (now_wall - overtake_phase_start_wall) >= total_s:
                        should_switch = True
                else:
                    if (now_wall - phase_start_wall) >= args.phase_duration_s:
                        should_switch = True

            if should_switch:
                if overtake_active_group_idx is not None:
                    _mark_overtake_group_world_time(overtake_active_group_idx, "end", sim_time)
                    overtake_active_group_idx = None
                _stop_segment_recording()
                # 切换阶段：清理残留车辆 + 重置前车行为 + 再次暂停15s
                phase_idx = (phase_idx + 1) % len(phases)
                phase_record_started["following"] = False
                phase_record_started["overtaking"] = False

                keep_ids = set()
                if world.player is not None:
                    keep_ids.add(world.player.id)
                if world.lead_vehicle is not None:
                    keep_ids.add(world.lead_vehicle.id)
                cleanup_other_vehicles(keep_ids=keep_ids)

                _, phase_text, exp_type_str, base_speed_ms = phases[phase_idx]
                # 进入超车阶段时：初始化超车速度序列与定时器
                if phases[phase_idx][0] == "overtaking":
                    overtake_group_idx = 0
                    overtake_in_cooldown = False
                    overtake_group_start_wall = None
                    overtake_phase_start_wall = None
                    overtake_prompt_until_wall = 0.0
                    overtake_speed_reached = False
                    overtake_active_group_idx = None
                    exp_type_str = "overtaking_groups"
                    base_speed_ms = 0.0
                else:
                    overtake_group_idx = 0
                    overtake_in_cooldown = False
                    overtake_group_start_wall = None
                    overtake_phase_start_wall = None
                    overtake_prompt_until_wall = 0.0
                    overtake_speed_reached = False
                    overtake_active_group_idx = None
                reset_lead_for_phase(exp_type_str, base_speed_ms)

                phase_start_wall = None
                pause_end_wall = time.time() + float(args.pre_start_pause_s)

    finally:
        if world is not None and overtake_active_group_idx is not None:
            sim_time = world.hud.simulation_time if hasattr(world.hud, "simulation_time") else None
            _mark_overtake_group_world_time(overtake_active_group_idx, "end", sim_time)
            overtake_active_group_idx = None
        if world is not None and world.data_collector and world.data_collector.is_collecting:
            sim_time = world.hud.simulation_time if hasattr(world.hud, "simulation_time") else None
            saved_path = world.data_collector.stop(world_end_time_s=sim_time)
            if saved_path:
                print(f"[前置熟悉实验] 数据已保存: {saved_path}")

        # 恢复同步设置
        if args.sync:
            sim_world.apply_settings(original_settings)
        if world is not None:
            try:
                world.destroy()
            except Exception:
                pass
        pygame.quit()


if __name__ == "__main__":
    main()

