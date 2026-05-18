#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
L3 轨迹回放（心理接管提示）

与 tools/replay_trajectory.py（L4 全自动回放）并列：车辆运动仍完全由 CSV 驱动，不改变 CARLA 控制。
默认截取仿真轴 [60,120]s（优先列 sim_time_s，无则 timestamp−首行），与 L4 相同；整段 CSV 请设 --playback-start-sim-offset-s 0 --playback-end-sim-s 0。
墙钟回放节拍优先 sim_time_s 相对片段首采样，无列则 timestamp−首采样。
空格键触发「接管」心理预期：播放 audio/takeover.mp3，HUD 显示接管状态约 1.5s 后自动回到自动驾驶提示。
左侧栏：行车信息与驾驶量区块标题按原规则居中；「--- L3 状态 ---」居中；「驾驶状态」标签与「自动驾驶/接管提示中」大号字左对齐；提示剩余与油门/制动/方向左对齐（CSV 有则显示，无则 --）。

暂停请按 P（避免与空格接管冲突）。

用法:
    python replay_trajectory_l3.py <csv_file> [与 replay_trajectory 相同的选项]

示例:
    python replay_trajectory_l3.py ../experiment_data/xxx/driving_data.csv --snap-to-road

实验开始时间（experiment_*）：自赛前倒计时结束之后起算；空格键记录的 seconds_since_experiment_start 与该起点一致。
"""

import argparse
import csv
import glob
import json
import math
import os
import sys
import time
from datetime import datetime

# CARLA egg（与 replay_trajectory 一致）
try:
    sys.path.append(
        glob.glob(
            '../../carla/dist/carla-*%d.%d-%s.egg'
            % (
                sys.version_info.major,
                sys.version_info.minor,
                'win-amd64' if os.name == 'nt' else 'linux-x86_64',
            )
        )[0]
    )
except IndexError:
    pass

import carla
import pygame

# 同目录模块
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import replay_trajectory as rt


def _default_takeover_audio():
    return os.path.abspath(os.path.join(_TOOLS_DIR, '..', 'audio', 'takeover.mp3'))


def _opt_float(row, key, default=None):
    v = row.get(key)
    if v in (None, ''):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_trajectory_l3(csv_file):
    """在 replay_trajectory.load_trajectory 基础上增加可选驾驶量字段。"""
    trajectory = []
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            point = {
                'timestamp': float(row['timestamp']),
                'sim_time_s': _opt_float(row, 'sim_time_s'),
                'ego_x': float(row['ego_pos_x']),
                'ego_y': float(row['ego_pos_y']),
                'ego_speed': float(row['ego_speed']),
                'ego_yaw': float(row.get('ego_yaw', 0)) if 'ego_yaw' in row else None,
                'ego_acceleration': _opt_float(row, 'ego_acceleration'),
                'ego_jerk': _opt_float(row, 'ego_jerk'),
                'throttle': _opt_float(row, 'throttle'),
                'brake': _opt_float(row, 'brake'),
                'steer': _opt_float(row, 'steer'),
            }

            if 'lead_pos_x' in row and row['lead_pos_x']:
                point['lead_x'] = float(row['lead_pos_x'])
                point['lead_y'] = float(row['lead_pos_y'])
                point['lead_yaw'] = (
                    float(row.get('lead_yaw', 0)) if 'lead_yaw' in row else None
                )
                point['lead_speed'] = float(row.get('lead_speed', 0))
                point['lead_acceleration'] = _opt_float(row, 'lead_acceleration')
            else:
                if (
                    'distance_headway' in row
                    and row['distance_headway']
                    and point['ego_yaw'] is not None
                ):
                    dist = float(row['distance_headway'])
                    rad = math.radians(point['ego_yaw'])
                    point['lead_x'] = point['ego_x'] + dist * math.cos(rad)
                    point['lead_y'] = point['ego_y'] + dist * math.sin(rad)
                    point['lead_yaw'] = point['ego_yaw']
                    point['lead_speed'] = float(row.get('lead_speed', 0))
                    point['lead_acceleration'] = _opt_float(row, 'lead_acceleration')
                else:
                    point['lead_x'] = None
                    point['lead_y'] = None
                    point['lead_yaw'] = None
                    point['lead_speed'] = 0
                    point['lead_acceleration'] = None

            if row.get('distance_headway') not in (None, ''):
                try:
                    point['distance_headway'] = float(row['distance_headway'])
                except (TypeError, ValueError):
                    point['distance_headway'] = None
            else:
                point['distance_headway'] = None
            if point['distance_headway'] is None and point.get('lead_x') is not None:
                point['distance_headway'] = math.hypot(
                    point['lead_x'] - point['ego_x'],
                    point['lead_y'] - point['ego_y'],
                )

            point['time_headway'] = _opt_float(row, 'time_headway')
            point['relative_speed'] = _opt_float(row, 'relative_speed')
            point['ttc'] = _opt_float(row, 'ttc')
            if point['relative_speed'] is None and point.get('lead_x') is not None:
                point['relative_speed'] = point['ego_speed'] - point.get(
                    'lead_speed', 0.0
                )
            if (
                point['time_headway'] is None
                and point.get('distance_headway') is not None
                and point['ego_speed'] > 0.5
            ):
                point['time_headway'] = point['distance_headway'] / point['ego_speed']

            trajectory.append(point)
    return trajectory


def draw_hud_l3(
    display,
    point,
    display_size,
    font_mono,
    font_mono_speed,
    font_title,
    takeover_until_monotonic,
):
    """左侧栏：行车信息标题居中；「--- L3 状态 ---」居中；驾驶状态与自动驾驶/接管提示中左对齐；驾驶量标题居中。"""
    dh = display_size[1]
    panel_w = 420
    px_left = 8
    base_bottom = rt.draw_hud(
        display,
        point,
        display_size,
        font_mono,
        font_mono_speed,
        font_title,
    )

    def blit_cx(surf, y):
        x = max(0, (panel_w - surf.get_width()) // 2)
        display.blit(surf, (x, y))

    py = base_bottom + 14
    line_h = 22

    now_m = time.monotonic()
    in_takeover = takeover_until_monotonic > now_m
    remain = max(0.0, takeover_until_monotonic - now_m) if in_takeover else 0.0

    mode_line = '接管提示中' if in_takeover else '自动驾驶'
    color_mode = (255, 220, 120) if in_takeover else (180, 220, 255)

    title = font_title.render('--- L3 状态 ---', True, (220, 225, 230))
    blit_cx(title, py)
    py += title.get_height() + 10

    sub_lbl = font_mono.render('驾驶状态', True, (190, 195, 200))
    display.blit(sub_lbl, (px_left, py))
    py += sub_lbl.get_height() + 6

    mode_big = font_mono_speed.render(mode_line, True, color_mode)
    display.blit(mode_big, (px_left, py))
    py += mode_big.get_height() + 10

    if in_takeover:
        m2 = font_mono.render(f'提示剩余: {remain:.1f} s', True, (255, 255, 255))
        display.blit(m2, (px_left, py))
        py += m2.get_height() + 12
    else:
        py += 6

    sep = font_mono.render('--- 驾驶量 ---', True, (160, 170, 180))
    blit_cx(sep, py)
    py += sep.get_height() + 8

    lines = [
        f'油门: {_fmt_opt(point.get("throttle"), ".3f")}',
        f'制动: {_fmt_opt(point.get("brake"), ".3f")}',
        f'方向: {_fmt_opt(point.get("steer"), ".3f")}',
    ]

    for line in lines:
        if py > dh - line_h:
            break
        surf = font_mono.render(line, True, (235, 238, 242))
        display.blit(surf, (px_left, py))
        py += line_h


def _fmt_opt(val, fmt):
    if val is None:
        return '--'
    try:
        return format(float(val), fmt)
    except (TypeError, ValueError):
        return '--'


def trigger_takeover_sound(audio_path):
    try:
        if os.path.isfile(audio_path):
            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.play()
        else:
            print(f'[L3] 未找到音频文件: {audio_path}')
    except Exception as e:
        print(f'[L3] 播放音频失败: {e}')


def _default_l3_event_log_path(csv_path):
    csv_abs = os.path.abspath(csv_path)
    d = os.path.dirname(csv_abs)
    base = os.path.basename(csv_abs)
    root, _ = os.path.splitext(base)
    tag = rt._csv_dir_parent_subject_tag(csv_abs)
    stamp = rt._session_log_filename_stamp()
    return os.path.join(d, f'{root}_l3_events_{tag}_{stamp}.json')


def _write_l3_event_log(path, data):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def build_arg_parser():
    p = argparse.ArgumentParser(description='L3 轨迹回放（心理接管提示）')
    p.add_argument('csv_file', help='CSV数据文件路径')
    p.add_argument('--host', default='127.0.0.1', help='CARLA服务器IP')
    p.add_argument('-p', '--port', default=2000, type=int, help='CARLA服务器端口')
    p.add_argument('--speed', default=1.0, type=float, help='回放速度倍率 (默认1.0)')
    p.add_argument(
        '--seek-step-pct',
        default=1.0,
        type=float,
        help='进度跳转步长(占总帧百分比)。默认1%%',
    )
    p.add_argument(
        '--seek-big-step-pct',
        default=10.0,
        type=float,
        help='进度大步跳转(占总帧百分比)。默认10%%',
    )
    p.add_argument('--ego-vehicle', default='vehicle.audi.tt', help='自车蓝图')
    p.add_argument('--lead-vehicle', default='vehicle.tesla.model3', help='前车蓝图')
    p.add_argument('--loop', action='store_true', help='循环回放')
    p.add_argument('--res', default=None, help='窗口分辨率 WxH')
    p.add_argument('--width', default=1280, type=int, help='窗口宽度')
    p.add_argument('--height', default=720, type=int, help='窗口高度')
    p.add_argument('--display', default=0, type=int, help='显示器编号')
    p.add_argument('--fullscreen', action='store_true', help='全屏')
    p.add_argument('--no-lead', action='store_true', help='不显示前车')
    p.add_argument('--snap-to-road', action='store_true', help='贴地 z')
    p.add_argument('--snap-z-offset', default=0.12, type=float)
    p.add_argument('--lead-z-offset', default=-0.07, type=float)
    p.add_argument('--no-z-smooth', action='store_true')
    p.add_argument('--z-smooth-alpha', default=0.2, type=float)
    p.add_argument('--z-smooth-max-step', default=0.06, type=float)
    p.add_argument('--vehicle-physics', action='store_true')
    p.add_argument('--keep-world-weather', action='store_true')
    p.add_argument('--replay-weather', default='ClearNoon', metavar='NAME')
    p.add_argument('--replay-sun-overhead-forward', action='store_true')
    p.add_argument('--replay-sun-altitude-deg', default=89.0, type=float)
    p.add_argument('--replay-sun-yaw-offset-deg', default=0.0, type=float)
    p.add_argument('--gamma', default=2.2, type=float)
    p.add_argument(
        '--takeover-audio',
        default=_default_takeover_audio(),
        help='接管提示音频路径，默认项目 audio/takeover.mp3',
    )
    p.add_argument(
        '--takeover-duration-s',
        default=1.5,
        type=float,
        help='每次空格后「接管提示」持续时长（秒，墙钟时间）',
    )
    p.add_argument(
        '--l3-event-log',
        default=None,
        metavar='PATH',
        help=(
            '记录实验开始时间与空格按键的 JSON；默认与 CSV 同目录 '
            '<stem>_l3_events_<上级文件夹>_<被试文件夹>_<时间戳>.json'
        ),
    )
    p.add_argument(
        '--pre-start-countdown-s',
        default=10.0,
        type=float,
        help='正式回放前在起始帧上全屏倒计时（秒），0 关闭；默认 5',
    )
    p.add_argument(
        '--playback-start-sim-offset-s',
        default=60.0,
        type=float,
        help=(
            '截取/起点匹配的仿真轴下界（秒），闭区间；优先 CSV 列 sim_time_s'
            '，无则用 timestamp−首帧。默认 60。与 --playback-end-sim-s 均为 0 时不截取整条 CSV'
        ),
    )
    p.add_argument(
        '--playback-end-sim-s',
        default=120.0,
        type=float,
        help=(
            '截取仿真轴上界（秒），闭区间；优先 sim_time_s，无则 timestamp−首帧。'
            '默认 120；≤0 表示截取到末尾；墙钟节拍与 L4 一致（sim_time_s 优先）'
        ),
    )
    return p


def main():
    argparser = build_arg_parser()
    args = argparser.parse_args()

    if args.res:
        try:
            args.width, args.height = [int(x) for x in args.res.split('x')]
        except ValueError:
            argparser.error('--res 格式应为 WxH')
    if args.gamma <= 0:
        argparser.error('--gamma 应为正数')
    if args.replay_sun_overhead_forward and args.keep_world_weather:
        argparser.error('--replay-sun-overhead-forward 与 --keep-world-weather 冲突')
    if args.replay_sun_altitude_deg < 0 or args.replay_sun_altitude_deg > 90:
        argparser.error('--replay-sun-altitude-deg 应在 0~90')
    if (
        not args.keep_world_weather
        and getattr(carla.WeatherParameters, args.replay_weather, None) is None
    ):
        avail = rt.list_weather_preset_names()
        preview = ', '.join(avail[:24])
        argparser.error(
            f'--replay-weather 无效: {args.replay_weather!r}。示例: {preview}'
        )
    if args.takeover_duration_s <= 0:
        argparser.error('--takeover-duration-s 应为正数')
    if args.pre_start_countdown_s < 0:
        argparser.error('--pre-start-countdown-s 不能为负')
    if args.playback_start_sim_offset_s < 0:
        argparser.error('--playback-start-sim-offset-s 不能为负')
    pe = float(getattr(args, 'playback_end_sim_s', 0.0) or 0.0)
    ps = float(args.playback_start_sim_offset_s)
    if pe > 0.0 and pe <= ps:
        argparser.error(
            '--playback-end-sim-s 必须大于 --playback-start-sim-offset-s（二者均为正时）'
        )

    print(f'加载轨迹: {args.csv_file}')
    trajectory = load_trajectory_l3(args.csv_file)
    print(f'轨迹点数: {len(trajectory)}')
    if not trajectory:
        print('错误: 轨迹为空')
        return

    trajectory = rt.estimate_yaw(trajectory)

    lo_win = float(getattr(args, 'playback_start_sim_offset_s', 0.0) or 0.0)
    hi_win = float(getattr(args, 'playback_end_sim_s', 0.0) or 0.0)
    csv_anchor_before_crop = trajectory[0]['timestamp']
    n_before_crop = len(trajectory)
    did_crop_segment = lo_win > 0.0 or hi_win > 0.0
    if did_crop_segment:
        trajectory = rt.crop_trajectory_by_csv_sim_window(trajectory, lo_win, hi_win)
        hi_txt = f'{hi_win:g}' if hi_win > 0.0 else '+∞'
        print(
            f'已截取仿真轴 ∈ [{lo_win:g}, {hi_txt}] s（优先列 sim_time_s，否则 timestamp−首行）：'
            f'{n_before_crop} → {len(trajectory)} 点'
        )
        if not trajectory:
            print('错误: 截取后轨迹为空')
            return
        args.playback_start_sim_offset_s = 0.0
        args.playback_end_sim_s = 0.0

    has_lead = trajectory[0].get('lead_x') is not None and not args.no_lead
    print(f"前车数据: {'有' if has_lead else '无'}")

    l3_log_path = os.path.abspath(
        args.l3_event_log or _default_l3_event_log_path(args.csv_file)
    )
    l3_events = {
        'schema_version': 1,
        'session_id': None,
        'l3_event_log': l3_log_path,
        'csv_file': os.path.abspath(args.csv_file),
        'csv_sim_anchor_original': csv_anchor_before_crop,
        'replay_sim_window_csv_lo_s': lo_win if lo_win > 0.0 else None,
        'replay_sim_window_csv_hi_s': hi_win if hi_win > 0.0 else None,
        'trajectory_first_timestamp': trajectory[0]['timestamp'],
        'takeover_duration_s': float(args.takeover_duration_s),
        'playback_cycle_index': None,
        'experiment_start_system_local': None,
        'experiment_start_monotonic_s': None,
        'experiment_start_wall_time_s': None,
        'experiment_end_system_local': None,
        'experiment_end_monotonic_s': None,
        'experiment_end_wall_time_s': None,
        'experiment_duration_wall_s': None,
        'session_end_system_local': None,
        'cycles': [],
        'space_presses': [],
    }

    pygame.init()
    pygame.font.init()
    pygame.mixer.init()
    font_mono, font_mono_speed, font_title = rt.make_replay_hud_fonts()
    font_countdown = rt.make_countdown_font()

    display_flags = pygame.HWSURFACE | pygame.DOUBLEBUF
    if args.fullscreen:
        display_flags |= pygame.FULLSCREEN
    display = pygame.display.set_mode(
        (args.width, args.height),
        display_flags,
        display=args.display,
    )
    pygame.display.set_caption('L3 轨迹回放 - 空格接管提示')
    clock = pygame.time.Clock()

    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    world = client.get_world()

    settings = world.get_settings()
    original_settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)

    if not args.keep_world_weather:
        if rt.apply_replay_weather(world, args.replay_weather):
            print(f'回放: 天气预设 {args.replay_weather}')
        else:
            print('回放: 设置天气失败，保持服务器天气')

    road_z = rt.make_road_z_resolver(
        world,
        args.snap_to_road,
        args.snap_z_offset,
        fallback_z=0.5,
    )
    use_z_smooth = args.snap_to_road and not args.no_z_smooth
    if args.z_smooth_alpha <= 0 or args.z_smooth_alpha > 1:
        argparser.error('--z-smooth-alpha 应在 (0, 1]')
    if args.z_smooth_max_step < 0:
        argparser.error('--z-smooth-max-step 不能为负')
    z_max_step = args.z_smooth_max_step if use_z_smooth else 0.0
    ego_z_smoother = rt.ZSmoother(args.z_smooth_alpha, max_step_m=z_max_step)
    lead_z_smoother = rt.ZSmoother(args.z_smooth_alpha, max_step_m=z_max_step)
    last_applied_idx = None

    try:
        for a in world.get_actors().filter('vehicle.*'):
            rn = a.attributes.get('role_name') or ''
            if rn in ('hero', 'lead_vehicle'):
                try:
                    a.destroy()
                except Exception:
                    pass
        for _ in range(5):
            world.tick()
    except Exception:
        pass

    bp_library = world.get_blueprint_library()
    ego_bp = bp_library.find(args.ego_vehicle)
    ego_bp.set_attribute('role_name', 'hero')
    if ego_bp.has_attribute('color'):
        ego_bp.set_attribute('color', '255,255,255')

    start = trajectory[0]
    z0_ego = road_z(start['ego_x'], start['ego_y'])
    ego_spawn = carla.Transform(
        carla.Location(x=start['ego_x'], y=start['ego_y'], z=z0_ego),
        carla.Rotation(yaw=start['ego_yaw'] if start['ego_yaw'] else 0),
    )
    ego_vehicle = world.spawn_actor(ego_bp, ego_spawn)
    print(f'自车已生成: {ego_vehicle.type_id}')

    lead_vehicle = None
    if has_lead:
        lead_bp = bp_library.find(args.lead_vehicle)
        lead_bp.set_attribute('role_name', 'lead_vehicle')
        if lead_bp.has_attribute('color'):
            lead_bp.set_attribute('color', '0,0,255')
        z0_lead = road_z(start['lead_x'], start['lead_y']) + args.lead_z_offset
        lead_spawn = carla.Transform(
            carla.Location(x=start['lead_x'], y=start['lead_y'], z=z0_lead),
            carla.Rotation(yaw=start['lead_yaw'] if start['lead_yaw'] else 0),
        )
        lead_vehicle = world.spawn_actor(lead_bp, lead_spawn)
        print(f'前车已生成: {lead_vehicle.type_id}')

    if not args.vehicle_physics:
        for v in (ego_vehicle, lead_vehicle):
            if v is None:
                continue
            try:
                v.set_simulate_physics(False)
            except Exception:
                pass

    camera = rt.DriverCamera(
        world, ego_vehicle, args.width, args.height, gamma=args.gamma
    )
    for _ in range(10):
        world.tick()

    print(f'\n开始 L3 回放 (速度: {args.speed}x)')
    print('空格: 心理接管提示  |  P: 暂停/继续  |  +/- 速度  |  ←/→ PgUp/Dn 跳转')
    print(f'接管提示时长: {args.takeover_duration_s}s，音频: {args.takeover_audio}')
    print(f'事件记录(JSON): {l3_log_path}')
    if did_crop_segment:
        hi_desc = f'{hi_win:g}' if hi_win > 0.0 else '+∞'
        print(
            '已按仿真轴（优先 sim_time_s）截取；墙钟以 sim_time_s 相对片段首行为准（≈原轴 '
            f'[{lo_win:g}, {hi_desc}] s）；'
            f'正式回放前: {args.pre_start_countdown_s}s 中央倒计时（0=关闭）'
        )
    else:
        end_h = (
            f'；sim_time≥{args.playback_end_sim_s:g}s 时结束（本帧播完）'
            if float(getattr(args, 'playback_end_sim_s', 0.0) or 0.0) > 0.0
            else ''
        )
        print(
            f'正式回放前: {args.pre_start_countdown_s}s 中央倒计时（0=关闭）；'
            f'从仿真轴≥{args.playback_start_sim_offset_s}s 的首帧起播{end_h}'
        )

    takeover_until_m = 0.0

    try:
        running = True
        paused = False
        speed_mult = args.speed
        play_start_ts = trajectory[0]['timestamp']
        traj0_pt = trajectory[0]
        playback_end_cap_s = float(getattr(args, 'playback_end_sim_s', 0.0) or 0.0)
        playback_cycle_index = 0

        sun_tune = bool(args.replay_sun_overhead_forward)
        sun_alt = float(args.replay_sun_altitude_deg)
        sun_yaw_off = float(args.replay_sun_yaw_offset_deg)

        def maybe_replay_sun(i):
            if not sun_tune:
                return
            pt = trajectory[i]
            y = pt.get('ego_yaw')
            rt.sync_replay_sun(world, sun_alt, y if y is not None else 0.0, sun_yaw_off)

        while running:
            seek_step_frames = max(
                1, int(len(trajectory) * (args.seek_step_pct / 100.0))
            )
            seek_big_step_frames = max(
                1, int(len(trajectory) * (args.seek_big_step_pct / 100.0))
            )

            def _finalize_l3_playback_cycle():
                end = rt.session_clock_snapshot()
                for rec in reversed(l3_events['cycles']):
                    if rec.get('playback_cycle_index') != playback_cycle_index:
                        continue
                    rec['experiment_end_system_local'] = end['ts_system_local']
                    rec['experiment_end_wall_time_s'] = end['wall_time_s']
                    rec['experiment_end_monotonic_s'] = end['monotonic_s']
                    t0 = rec.get('experiment_start_wall_time_s')
                    if t0 is not None:
                        rec['experiment_duration_wall_s'] = (
                            end['wall_time_s'] - float(t0)
                        )
                    break
                l3_events['experiment_end_system_local'] = end['ts_system_local']
                l3_events['experiment_end_wall_time_s'] = end['wall_time_s']
                l3_events['experiment_end_monotonic_s'] = end['monotonic_s']
                t0r = l3_events.get('experiment_start_wall_time_s')
                if t0r is not None:
                    l3_events['experiment_duration_wall_s'] = (
                        end['wall_time_s'] - float(t0r)
                    )
                try:
                    _write_l3_event_log(l3_log_path, l3_events)
                except Exception:
                    pass

            def apply_frame(idx):
                nonlocal last_applied_idx
                p = trajectory[idx]
                if use_z_smooth:
                    if last_applied_idx is None or abs(idx - last_applied_idx) != 1:
                        ego_z_smoother.reset()
                        lead_z_smoother.reset()
                    last_applied_idx = idx
                    z_ego = ego_z_smoother.smooth(road_z(p['ego_x'], p['ego_y']))
                else:
                    z_ego = road_z(p['ego_x'], p['ego_y'])

                ego_transform = carla.Transform(
                    carla.Location(x=p['ego_x'], y=p['ego_y'], z=z_ego),
                    carla.Rotation(yaw=p['ego_yaw'] if p['ego_yaw'] else 0),
                )
                ego_vehicle.set_transform(ego_transform)
                if not args.vehicle_physics:
                    rt._stabilize_kinematic_vehicle_visuals(ego_vehicle)

                if args.vehicle_physics and p['ego_speed'] > 0 and p['ego_yaw'] is not None:
                    rad = math.radians(p['ego_yaw'])
                    ego_vehicle.set_target_velocity(
                        carla.Vector3D(
                            x=p['ego_speed'] * math.cos(rad),
                            y=p['ego_speed'] * math.sin(rad),
                            z=0,
                        )
                    )

                if lead_vehicle and p.get('lead_x') is not None:
                    if use_z_smooth:
                        z_lead = (
                            lead_z_smoother.smooth(
                                road_z(p['lead_x'], p['lead_y'])
                            )
                            + args.lead_z_offset
                        )
                    else:
                        z_lead = road_z(p['lead_x'], p['lead_y']) + args.lead_z_offset
                    lead_vehicle.set_transform(
                        carla.Transform(
                            carla.Location(x=p['lead_x'], y=p['lead_y'], z=z_lead),
                            carla.Rotation(
                                yaw=p['lead_yaw'] if p.get('lead_yaw') else 0
                            ),
                        )
                    )
                    if not args.vehicle_physics:
                        rt._stabilize_kinematic_vehicle_visuals(lead_vehicle)
                    lead_speed = p.get('lead_speed', 0)
                    if (
                        args.vehicle_physics
                        and lead_speed > 0
                        and p.get('lead_yaw') is not None
                    ):
                        rad = math.radians(p['lead_yaw'])
                        lead_vehicle.set_target_velocity(
                            carla.Vector3D(
                                x=lead_speed * math.cos(rad),
                                y=lead_speed * math.sin(rad),
                                z=0,
                            )
                        )

                maybe_replay_sun(idx)

            def render_frame(point_idx):
                apply_frame(point_idx)
                world.tick()
                camera.render(display)
                draw_hud_l3(
                    display,
                    trajectory[point_idx],
                    display.get_size(),
                    font_mono,
                    font_mono_speed,
                    font_title,
                    takeover_until_m,
                )
                pygame.display.flip()

            start_idx = rt.resolve_playback_start_frame_index(
                trajectory, play_start_ts, float(args.playback_start_sim_offset_s)
            )
            if start_idx > 0:
                sim0 = rt.trajectory_point_sim_axis_s(
                    trajectory[start_idx], play_start_ts
                )
                print(
                    f'回放起点: 仿真轴≥{args.playback_start_sim_offset_s}s 的首帧 index={start_idx} '
                    f'(该帧 sim_axis={sim0:.2f}s；墙钟优先 sim_time_s 相对首采样)'
                )
            dw_cd, dh_cd = display.get_size()
            if float(args.pre_start_countdown_s) > 0:
                t_hold_end = time.time() + float(args.pre_start_countdown_s)
                while time.time() < t_hold_end and running:
                    remaining = max(0.0, t_hold_end - time.time())
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            running = False
                        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                            running = False
                    if not running:
                        break
                    apply_frame(start_idx)
                    world.tick()
                    camera.render(display)
                    draw_hud_l3(
                        display,
                        trajectory[start_idx],
                        (dw_cd, dh_cd),
                        font_mono,
                        font_mono_speed,
                        font_title,
                        takeover_until_m,
                    )
                    lines = [f'倒计时: {rt._fmt_mm_ss(remaining)}']
                    rt.draw_center_countdown_lines(
                        display, font_countdown, lines, dw_cd, dh_cd
                    )
                    pygame.display.flip()
                    clock.tick(30)
            if not running:
                break

            exp_start_m = time.monotonic()
            exp_wall_s = time.time()
            now_local = datetime.now().astimezone()
            exp_start_system_local = now_local.isoformat(timespec='microseconds')
            if playback_cycle_index == 0:
                sid = rt.make_session_filter_id(now_local, args.csv_file, 'L3')
                l3_events['session_id'] = sid
                print('')
                print('========== 会话标识（检索用 / JSON 字段 session_id）==========')
                print(f'  session_id:           {sid}')
                print(f'  experiment_start_system_local: {exp_start_system_local}')
                print(' （计时起点：倒计时已结束）')
                print('==============================================================')
                print('')
            cycle_rec = {
                'playback_cycle_index': playback_cycle_index,
                'experiment_start_system_local': exp_start_system_local,
                'experiment_start_monotonic_s': exp_start_m,
                'experiment_start_wall_time_s': exp_wall_s,
                'experiment_end_system_local': None,
                'experiment_end_monotonic_s': None,
                'experiment_end_wall_time_s': None,
                'experiment_duration_wall_s': None,
            }
            l3_events['cycles'].append(cycle_rec)
            l3_events['playback_cycle_index'] = playback_cycle_index
            l3_events['experiment_start_system_local'] = exp_start_system_local
            l3_events['experiment_start_monotonic_s'] = exp_start_m
            l3_events['experiment_start_wall_time_s'] = exp_wall_s
            _write_l3_event_log(l3_log_path, l3_events)

            cur_sim0 = rt.playback_elapsed_sim_s(
                trajectory[start_idx], play_start_ts, traj0_pt
            )
            wall_start = time.time() - (cur_sim0 / speed_mult)
            frame_idx = start_idx

            while frame_idx < len(trajectory) and running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            running = False
                        elif event.key == pygame.K_SPACE:
                            takeover_until_m = time.monotonic() + float(
                                args.takeover_duration_s
                            )
                            trigger_takeover_sound(args.takeover_audio)
                            print('[L3] 接管提示（心理预期）')
                            now_m = time.monotonic()
                            pt = trajectory[frame_idx]
                            t0 = l3_events.get('experiment_start_monotonic_s')
                            press = {
                                'wall_time_system_local': datetime.now().astimezone().isoformat(
                                    timespec='microseconds'
                                ),
                                'monotonic_s': now_m,
                                'seconds_since_experiment_start': (
                                    (now_m - t0) if t0 is not None else None
                                ),
                                'playback_cycle': playback_cycle_index,
                                'trajectory_frame_index': frame_idx,
                                'csv_timestamp': pt['timestamp'],
                                'sim_elapsed_s': rt.playback_elapsed_sim_s(
                                    pt, play_start_ts, traj0_pt
                                ),
                            }
                            l3_events['space_presses'].append(press)
                            _write_l3_event_log(l3_log_path, l3_events)
                            if paused:
                                render_frame(frame_idx)
                        elif event.key == pygame.K_p:
                            paused = not paused
                            print('暂停' if paused else '继续')
                            if not paused:
                                cur = trajectory[frame_idx]
                                cur_sim = rt.playback_elapsed_sim_s(
                                    cur, play_start_ts, traj0_pt
                                )
                                wall_start = time.time() - (cur_sim / speed_mult)
                        elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                            speed_mult = min(10.0, speed_mult + 0.5)
                            cur = trajectory[frame_idx]
                            cur_sim = rt.playback_elapsed_sim_s(
                                cur, play_start_ts, traj0_pt
                            )
                            wall_start = time.time() - (cur_sim / speed_mult)
                        elif event.key == pygame.K_MINUS:
                            speed_mult = max(0.1, speed_mult - 0.5)
                            cur = trajectory[frame_idx]
                            cur_sim = rt.playback_elapsed_sim_s(
                                cur, play_start_ts, traj0_pt
                            )
                            wall_start = time.time() - (cur_sim / speed_mult)
                        elif event.key == pygame.K_RIGHT:
                            new_idx = min(len(trajectory) - 1, frame_idx + seek_step_frames)
                            if new_idx != frame_idx:
                                frame_idx = new_idx
                                cur_sim = rt.playback_elapsed_sim_s(
                                    trajectory[frame_idx],
                                    play_start_ts,
                                    traj0_pt,
                                )
                                wall_start = time.time() - (cur_sim / speed_mult)
                                if paused:
                                    render_frame(frame_idx)
                        elif event.key == pygame.K_LEFT:
                            new_idx = max(0, frame_idx - seek_step_frames)
                            if new_idx != frame_idx:
                                frame_idx = new_idx
                                cur_sim = rt.playback_elapsed_sim_s(
                                    trajectory[frame_idx],
                                    play_start_ts,
                                    traj0_pt,
                                )
                                wall_start = time.time() - (cur_sim / speed_mult)
                                if paused:
                                    render_frame(frame_idx)
                        elif event.key == pygame.K_PAGEUP:
                            new_idx = min(
                                len(trajectory) - 1, frame_idx + seek_big_step_frames
                            )
                            if new_idx != frame_idx:
                                frame_idx = new_idx
                                cur_sim = rt.playback_elapsed_sim_s(
                                    trajectory[frame_idx],
                                    play_start_ts,
                                    traj0_pt,
                                )
                                wall_start = time.time() - (cur_sim / speed_mult)
                                if paused:
                                    render_frame(frame_idx)
                        elif event.key == pygame.K_PAGEDOWN:
                            new_idx = max(0, frame_idx - seek_big_step_frames)
                            if new_idx != frame_idx:
                                frame_idx = new_idx
                                cur_sim = rt.playback_elapsed_sim_s(
                                    trajectory[frame_idx],
                                    play_start_ts,
                                    traj0_pt,
                                )
                                wall_start = time.time() - (cur_sim / speed_mult)
                                if paused:
                                    render_frame(frame_idx)

                if paused:
                    apply_frame(frame_idx)
                    world.tick()
                    camera.render(display)
                    draw_hud_l3(
                        display,
                        trajectory[frame_idx],
                        display.get_size(),
                        font_mono,
                        font_mono_speed,
                        font_title,
                        takeover_until_m,
                    )
                    pygame.display.flip()
                    clock.tick(30)
                    continue

                point = trajectory[frame_idx]
                sim_elapsed = rt.playback_elapsed_sim_s(
                    point, play_start_ts, traj0_pt
                )
                if playback_end_cap_s > 0.0 and sim_elapsed > playback_end_cap_s:
                    break
                target_time = sim_elapsed / speed_mult
                while True:
                    elapsed = time.time() - wall_start
                    if target_time <= elapsed:
                        break
                    rem = target_time - elapsed
                    if rem > 0.05:
                        time.sleep(0.05)
                        world.tick()
                    else:
                        time.sleep(rem)

                apply_frame(frame_idx)
                world.tick()
                camera.render(display)
                draw_hud_l3(
                    display,
                    point,
                    display.get_size(),
                    font_mono,
                    font_mono_speed,
                    font_title,
                    takeover_until_m,
                )
                pygame.display.flip()
                clock.tick(60)
                if playback_end_cap_s > 0.0 and sim_elapsed >= playback_end_cap_s:
                    frame_idx += 1
                    break
                frame_idx += 1

            _finalize_l3_playback_cycle()

            if not args.loop:
                print('\n回放完成')
                while running:
                    world.tick()
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT or (
                            event.type == pygame.KEYDOWN
                            and event.key == pygame.K_ESCAPE
                        ):
                            running = False
                    clock.tick(30)
            else:
                print('\n循环回放...')
                playback_cycle_index += 1

    except KeyboardInterrupt:
        print('\n用户中断')
    finally:
        _end = rt.session_clock_snapshot()
        l3_events['session_end_system_local'] = _end['ts_system_local']
        if l3_events.get('experiment_end_system_local') is None:
            l3_events['experiment_end_system_local'] = _end['ts_system_local']
            l3_events['experiment_end_wall_time_s'] = _end['wall_time_s']
            l3_events['experiment_end_monotonic_s'] = _end['monotonic_s']
            t0 = l3_events.get('experiment_start_wall_time_s')
            if t0 is not None:
                l3_events['experiment_duration_wall_s'] = (
                    _end['wall_time_s'] - float(t0)
                )
            for rec in reversed(l3_events.get('cycles') or []):
                if rec.get('experiment_end_system_local') is not None:
                    continue
                rec['experiment_end_system_local'] = _end['ts_system_local']
                rec['experiment_end_wall_time_s'] = _end['wall_time_s']
                rec['experiment_end_monotonic_s'] = _end['monotonic_s']
                t0c = rec.get('experiment_start_wall_time_s')
                if t0c is not None:
                    rec['experiment_duration_wall_s'] = (
                        _end['wall_time_s'] - float(t0c)
                    )
                break
        try:
            _write_l3_event_log(l3_log_path, l3_events)
        except Exception:
            pass
        world.apply_settings(original_settings)
        camera.destroy()
        ego_vehicle.destroy()
        if lead_vehicle:
            lead_vehicle.destroy()
        pygame.quit()
        print('资源已清理')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f'\n错误: {e}')
