#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
超车轨迹顺序回放（exp1_o → exp2_o → exp3_o）

选择根目录，其下须有三个子文件夹，文件夹名以 exp1_o、exp2_o、exp3_o 结尾（或完全等于），
按顺序播放各文件夹内同名 CSV（默认 driving_data.csv）。

每个 CSV 开放在首帧停留若干秒，屏幕中央显示「倒计时: MM:SS」（与主实验冷却 HUD 风格一致），
再按时间戳正常回放。其余逻辑与 tools/replay_trajectory.py 相同。

用法:
    python replay_trajectory_overtaking.py <overtake_root> [与 replay_trajectory 相同的选项]

示例:
    python replay_trajectory_overtaking.py ../phase2/my_run --snap-to-road
    python replay_trajectory_overtaking.py ../phase2/my_run --csv-name driving_data.csv --hold-first-frame-s 10
"""

import argparse
import glob
import os
import sys
from datetime import datetime, timezone

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

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import replay_trajectory as rt


EXP_ORDER = ('exp1_o', 'exp2_o', 'exp3_o')


def _pick_subdir_for_suffix(root, suffix):
    """根目录下子文件夹：优先完全等于 suffix，否则名称以 suffix 结尾。"""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return None
    exact = None
    suff = []
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        if name == suffix:
            exact = p
        elif name.endswith(suffix):
            suff.append((name, p))
    if exact:
        return exact
    suff.sort(key=lambda x: x[0])
    return suff[0][1] if suff else None


def discover_overtaking_csvs(overtake_root, csv_name):
    """返回 [(exp1_o, csv_path), (exp2_o, ...), ...]。"""
    missing = []
    out = []
    for suf in EXP_ORDER:
        d = _pick_subdir_for_suffix(overtake_root, suf)
        if d is None:
            missing.append(suf)
            continue
        csv_path = os.path.join(d, csv_name)
        if not os.path.isfile(csv_path):
            missing.append(f'{suf} ({csv_path})')
            continue
        out.append((suf, os.path.abspath(csv_path)))
    if len(out) != len(EXP_ORDER):
        raise SystemExit(
            '未找到全部三组数据目录或 CSV。需要根目录下存在 *exp1_o、*exp2_o、*exp3_o 子文件夹，'
            f'且内含 {csv_name}。缺失: {", ".join(missing)}'
        )
    return out


def main():
    mini = argparse.ArgumentParser(add_help=False)
    mini.add_argument(
        'overtake_root',
        help='含 exp1_o / exp2_o / exp3_o 子文件夹的根目录',
    )
    mini.add_argument(
        '--csv-name',
        default='driving_data.csv',
        help='各子文件夹内 CSV 文件名，默认 driving_data.csv',
    )
    mini.add_argument(
        '--hold-first-frame-s',
        type=float,
        default=10.0,
        help='每条轨迹开始前在首帧停留的秒数（中央倒计时），默认 10',
    )
    mini_args, rest = mini.parse_known_args()

    rt_parser = rt.build_replay_argparser(include_csv_positional=False)
    rt_args = rt_parser.parse_args(rest)

    args = argparse.Namespace(**vars(mini_args), **vars(rt_args))

    if args.res:
        try:
            args.width, args.height = [int(x) for x in args.res.split('x')]
        except ValueError:
            rt_parser.error('--res 格式应为 WxH，例如 1920x1080')
    rt.validate_replay_args(args, rt_parser)

    sequences = discover_overtaking_csvs(args.overtake_root, args.csv_name)
    print('超车顺序回放，轨迹:')
    for tag, p in sequences:
        print(f'  [{tag}] {p}')

    first_csv = sequences[0][1]
    session_log_path = os.path.abspath(
        args.replay_session_log
        or os.path.join(
            os.path.abspath(args.overtake_root),
            'overtake_replay_session.json',
        )
    )
    session_log = {
        'schema_version': 1,
        'kind': 'overtaking_sequence',
        'overtake_root': os.path.abspath(args.overtake_root),
        'replay_session_log': session_log_path,
        'csv_name': args.csv_name,
        'hold_first_frame_s': float(args.hold_first_frame_s),
        'sequences': [{'tag': t, 'csv': c} for t, c in sequences],
        'session_id': None,
        'playback_cycle_index': None,
        'experiment_start_utc': None,
        'experiment_start_monotonic_s': None,
        'experiment_start_wall_time_s': None,
        'cycles': [],
        'session_end_utc': None,
    }

    pygame.init()
    pygame.font.init()
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
    pygame.display.set_caption('超车轨迹回放 exp1_o→exp2_o→exp3_o')
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
    rt.validate_z_smooth_args(args, rt_parser, use_z_smooth)
    z_max_step = args.z_smooth_max_step if use_z_smooth else 0.0
    ego_z_smoother = rt.ZSmoother(args.z_smooth_alpha, max_step_m=z_max_step)
    lead_z_smoother = rt.ZSmoother(args.z_smooth_alpha, max_step_m=z_max_step)

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

    ego_vehicle = None
    lead_vehicle = None
    camera = None

    try:
        playback_cycle_index = 0
        for tag, csv_path in sequences:
            print(f'\n--- 加载 [{tag}] {csv_path} ---')
            trajectory = rt.load_trajectory(csv_path)
            if not trajectory:
                print(f'错误: 轨迹为空 {csv_path}')
                return
            trajectory = rt.estimate_yaw(trajectory)
            has_lead = trajectory[0].get('lead_x') is not None and not args.no_lead
            print(f'前车数据: {"有" if has_lead else "无"}')

            args.csv_file = csv_path

            rt.destroy_replay_actors(camera, ego_vehicle, lead_vehicle)
            camera, ego_vehicle, lead_vehicle = None, None, None

            ego_vehicle, lead_vehicle, camera = rt.spawn_replay_vehicles_and_camera(
                world, args, road_z, trajectory, has_lead
            )
            print(f'自车已生成: {ego_vehicle.type_id}')
            if lead_vehicle:
                print(f'前车已生成: {lead_vehicle.type_id}')

            hold_lines = [f'超车回放 {tag}', os.path.basename(os.path.dirname(csv_path))]

            running = rt.play_trajectory_once(
                args=args,
                world=world,
                ego_vehicle=ego_vehicle,
                lead_vehicle=lead_vehicle,
                camera=camera,
                display=display,
                clock=clock,
                trajectory=trajectory,
                font_mono=font_mono,
                font_mono_speed=font_mono_speed,
                font_title=font_title,
                font_countdown=font_countdown,
                road_z=road_z,
                use_z_smooth=use_z_smooth,
                ego_z_smoother=ego_z_smoother,
                lead_z_smoother=lead_z_smoother,
                session_log=session_log,
                session_log_path=session_log_path,
                playback_cycle_index=playback_cycle_index,
                hold_first_frame_s=float(args.hold_first_frame_s),
                hold_extra_lines=hold_lines,
                session_mode_tag='Overtake',
                playback_start_sim_offset_s=0.0,
            )
            playback_cycle_index += 1
            if not running:
                break

        if running:
            print('\n全部三组超车回放完成')
            while running:
                world.tick()
                for event in pygame.event.get():
                    if event.type == pygame.QUIT or (
                        event.type == pygame.KEYDOWN
                        and event.key == pygame.K_ESCAPE
                    ):
                        running = False
                clock.tick(30)

    except KeyboardInterrupt:
        print('\n用户中断')
    finally:
        session_log['session_end_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            rt._write_replay_session_log(session_log_path, session_log)
        except Exception:
            pass
        world.apply_settings(original_settings)
        rt.destroy_replay_actors(camera, ego_vehicle, lead_vehicle)
        pygame.quit()
        print('资源已清理')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f'\n错误: {e}')
