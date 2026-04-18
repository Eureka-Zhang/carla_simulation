#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
前置熟悉实验（默认采集数据）

两个阶段手动切换键：F4（与主脚本一致）、F11、Insert、F12。
按键拦截在 parse_events 之前，避免 cabin 模式下被主脚本的 F4 处理吞掉。
1) 跟驰：按设定节奏进行不规则变速
2) 超车：每次进入阶段都会重生车辆并置零速度，冷却10s后提示“先进行跟驰 / 随后变道超车”

超车阶段最大时长 120s，超时后自动切回跟驰。
"""

import argparse
import os
import time
import math
from datetime import datetime
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


def draw_center_message(display, font_large, text: str, width: int, height: int):
    """居中显示提示词（无倒计时）。"""
    color = (255, 255, 255)
    shadow_color = (0, 0, 0)

    lines = []
    if text:
        for part in str(text).splitlines():
            lines.append(part)
    if not lines:
        return

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


def draw_top_right_countdown(display, font_small, text: str, width: int):
    """右上角显示实验倒计时。"""
    if not text:
        return
    color = (255, 255, 255)
    shadow_color = (0, 0, 0)
    surf = font_small.render(text, True, color)
    shadow = font_small.render(text, True, shadow_color)
    x = max(12, width - surf.get_width() - 12)
    y = 12
    display.blit(shadow, (x + 2, y + 2))
    display.blit(surf, (x, y))


def draw_center_countdown(display, font_large, text: str, width: int, height: int):
    """屏幕中央显示冷却倒计时。"""
    if not text:
        return
    color = (255, 255, 255)
    shadow_color = (0, 0, 0)
    surf = font_large.render(text, True, color)
    shadow = font_large.render(text, True, shadow_color)
    x = (width - surf.get_width()) // 2
    y = (height - surf.get_height()) // 2
    display.blit(shadow, (x + 2, y + 2))
    display.blit(surf, (x, y))


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
    argparser.add_argument("--keyboard", action="store_true", help="使用键盘控制自车（默认使用驾驶舱）")
    argparser.add_argument("--cabin", action="store_true", help="使用驾驶舱控制自车（默认启用，可省略）")
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

    # 超车阶段（模仿主实验逻辑）
    argparser.add_argument("--overtake-speed-kmh", default=50.0, type=float, help="超车阶段前车目标速度（km/h）")
    argparser.add_argument("--overtake-cooldown-s", default=10.0, type=float, help="超车阶段冷却时长（秒），默认10s")
    argparser.add_argument("--overtake-max-duration-s", default=120.0, type=float, help="超车阶段最大时长（秒），默认120s")

    argparser.add_argument("--pre-start-pause-s", default=10.0, type=float, help="每阶段开始前暂停时间（秒），默认10s")
    argparser.add_argument("--spawn-right-offset", default=3.5, type=float, help="生成点向右偏移（米），默认3.5m（右车道）")

    args = argparser.parse_args()

    args.width, args.height = [int(x) for x in args.res.split("x")]
    if args.keyboard:
        args.input_mode = "keyboard"
    else:
        args.input_mode = "cabin"
    if args.cabin_echo_interval is None:
        args.cabin_echo_interval = 0.25 if args.input_mode == "cabin" else 0.0
    args.spawn_right_offset = abs(float(args.spawn_right_offset))

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
        font_small = pygame.font.Font(chinese_font, 32)
    else:
        font_large = pygame.font.Font(None, 64)
        font_small = pygame.font.Font(None, 32)

    # 阶段配置
    phases = [
        ("following", "请进行跟驰", "following_irregular", kmh_to_ms(args.follow_speed_kmh)),
        ("overtaking", "先进行跟驰\n随后变道超车", "overtaking", kmh_to_ms(args.overtake_speed_kmh)),
    ]

    running = True
    phase_idx = 0
    phase_segment_idx = 0
    phase_record_started = {"following": False, "overtaking": False}
    overtake_phase_start_wall = None
    overtake_cooldown_start_wall = None
    overtake_prompt_pending = False
    overtake_speed_reached = False
    center_prompt_text = ""
    center_prompt_until_wall = 0.0

    def show_center_prompt(text: str, seconds: float = 1.5):
        nonlocal center_prompt_text, center_prompt_until_wall
        center_prompt_text = str(text)
        center_prompt_until_wall = time.time() + max(0.0, float(seconds))

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
        hud.notification(f"分段采集开始: {phase_name}", seconds=1.8)

    def _stop_segment_recording():
        if world is None or world.data_collector is None or (not world.data_collector.is_collecting):
            return
        sim_time = world.hud.simulation_time if hasattr(world.hud, "simulation_time") else None
        saved_path = world.data_collector.stop(world_end_time_s=sim_time)
        if saved_path:
            print(f"[前置熟悉实验] 分段保存完成: {saved_path}")

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

    clock = pygame.time.Clock()

    pause_end_wall = time.time() + float(args.pre_start_pause_s)
    phase_start_wall = None

    def reset_ego_lead_to_zero():
        if world.lead_vehicle is not None:
            world.lead_vehicle.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
        if world.player is not None:
            world.player.set_target_velocity(carla.Vector3D(0.0, 0.0, 0.0))
            world.player.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))

    def switch_phase(new_phase_idx: int):
        nonlocal phase_idx, pause_end_wall, phase_start_wall
        nonlocal overtake_phase_start_wall, overtake_cooldown_start_wall, overtake_prompt_pending, overtake_speed_reached
        _stop_segment_recording()
        phase_record_started["following"] = False
        phase_record_started["overtaking"] = False

        phase_idx = new_phase_idx % len(phases)
        _, phase_text, exp_type_str, base_speed_ms = phases[phase_idx]

        hard_restart_world()
        reset_lead_for_phase(exp_type_str, base_speed_ms)
        reset_ego_lead_to_zero()

        phase_start_wall = None
        overtake_phase_start_wall = None
        overtake_prompt_pending = False
        overtake_speed_reached = False
        if phases[phase_idx][0] == "overtaking":
            overtake_cooldown_start_wall = time.time()
            pause_end_wall = 0.0
        else:
            overtake_cooldown_start_wall = None
            pause_end_wall = time.time() + float(args.pre_start_pause_s)

        phase_label_map = {"following": "前置实验-跟驰", "overtaking": "前置实验-超车"}
        phase_label = phase_label_map.get(phases[phase_idx][0], phase_text)
        hud.notification(phase_label, seconds=1.8)

    # 初始化第一阶段
    switch_phase(phase_idx)

    try:
        while running:
            # 同步模式：先推进 CARLA 时间
            if args.sync:
                sim_world.tick()
            else:
                sim_world.wait_for_tick()

            clock.tick_busy_loop(30)

            # 事件 + 自车控制
            now_wall = time.time()

            def _recompute_phase_flags():
                name = phases[phase_idx][0]
                pause_fa = (name == "following") and (time.time() < pause_end_wall)
                cool_oa = (
                    name == "overtaking"
                    and overtake_cooldown_start_wall is not None
                    and (time.time() - overtake_cooldown_start_wall) < float(args.overtake_cooldown_s)
                )
                return name, pause_fa, cool_oa, (pause_fa or cool_oa)

            current_phase_name, following_pause_active, overtaking_cooldown_active, phase_pause_active = _recompute_phase_flags()

            SWITCH_KEYS = (pygame.K_F4, pygame.K_F11, pygame.K_INSERT, pygame.K_F12)
            phase_switch_requested = False
            try:
                pending_keydowns = pygame.event.get(pygame.KEYDOWN)
            except Exception:
                pending_keydowns = []
            for _ev in pending_keydowns:
                if _ev.key == pygame.K_ESCAPE:
                    running = False
                elif _ev.key in SWITCH_KEYS:
                    phase_switch_requested = True
                else:
                    try:
                        pygame.event.post(_ev)
                    except Exception:
                        pass
            if phase_switch_requested:
                switch_phase(phase_idx + 1)
                now_wall = time.time()
                current_phase_name, following_pause_active, overtaking_cooldown_active, phase_pause_active = _recompute_phase_flags()

            if not running:
                break

            if args.input_mode == "keyboard":
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
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

            # 跟驰阶段：倒计时结束自动切换到超车
            if (
                current_phase_name == "following"
                and (not phase_pause_active)
                and (phase_start_wall is not None)
                and (now_wall - phase_start_wall) >= float(args.phase_duration_s)
            ):
                hud.notification("跟驰阶段结束，自动切换到超车", seconds=2.0)
                switch_phase(phase_idx + 1)
                now_wall = time.time()
                current_phase_name = phases[phase_idx][0]

            # 超车阶段：重生后先冷却10s，达到目标速度后提示超车，单次最大120s
            if current_phase_name == "overtaking" and (not phase_pause_active) and (phase_start_wall is not None):
                if overtake_phase_start_wall is None:
                    overtake_phase_start_wall = now_wall
                    overtake_prompt_pending = True
                    # 初始提示由下面「phase_start_wall is None」分支统一触发，这里不再重复

                if (not phase_record_started["overtaking"]) and world.lead_vehicle is not None:
                    lv0 = world.lead_vehicle.get_velocity()
                    lead_speed0 = math.sqrt(lv0.x * lv0.x + lv0.y * lv0.y + lv0.z * lv0.z)
                    if lead_speed0 > 0.2:
                        _start_segment_recording("overtaking")
                        phase_record_started["overtaking"] = True
                if overtake_prompt_pending and world.lead_vehicle is not None:
                    target_ms = kmh_to_ms(float(args.overtake_speed_kmh))
                    lv = world.lead_vehicle.get_velocity()
                    lead_speed = math.sqrt(lv.x * lv.x + lv.y * lv.y + lv.z * lv.z)
                    if lead_speed >= max(0.0, target_ms * 0.95):
                        overtake_prompt_pending = False
                        overtake_speed_reached = True
                        show_center_prompt("可超车", seconds=1.5)

                if overtake_phase_start_wall is not None and (now_wall - overtake_phase_start_wall) >= float(args.overtake_max_duration_s):
                    hud.notification("超车阶段已达 120s，自动切回跟驰", seconds=2.0)
                    switch_phase(0)
                    now_wall = time.time()
                    current_phase_name = phases[phase_idx][0]

            # HUD 更新（不调用 World.tick，避免 lead_controller 在暂停期间被推进）
            world.hud.tick(world, clock)

            # 渲染
            world.render(display)

            # 绘制阶段大字/倒计时（覆盖在渲染之上）
            if following_pause_active:
                remaining = pause_end_wall - now_wall
                draw_center_countdown(display, font_large, f"倒计时: {fmt_mm_ss(remaining)}", args.width, args.height)
            elif overtaking_cooldown_active:
                reset_ego_lead_to_zero()
                remaining = float(args.overtake_cooldown_s) - (now_wall - overtake_cooldown_start_wall)
                draw_center_countdown(display, font_large, f"倒计时: {fmt_mm_ss(remaining)}", args.width, args.height)
            else:
                if phase_start_wall is None:
                    phase_start_wall = now_wall
                    _, phase_text, _, _ = phases[phase_idx]
                    show_center_prompt(phase_text, seconds=1.5)
                if phases[phase_idx][0] == "following":
                    remaining = args.phase_duration_s - (now_wall - phase_start_wall)
                    draw_top_right_countdown(display, font_small, f"倒计时: {fmt_mm_ss(remaining)}", args.width)
                elif phases[phase_idx][0] == "overtaking":
                    remaining = float(args.overtake_max_duration_s) - (now_wall - phase_start_wall)
                    draw_top_right_countdown(display, font_small, f"倒计时: {fmt_mm_ss(remaining)}", args.width)
            if center_prompt_text and now_wall < center_prompt_until_wall:
                draw_center_message(display, font_large, center_prompt_text, args.width, args.height)
            pygame.display.flip()

    finally:
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

