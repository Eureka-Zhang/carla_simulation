#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
超车轨迹顺序回放（exp1_o → exp2_o → exp3_o）

选择根目录，其下须有三个子文件夹，文件夹名以 exp1_o、exp2_o、exp3_o 结尾（或完全等于），
按顺序播放各文件夹内同名 CSV（默认 driving_data.csv）。

每个 CSV 开放在首帧停留若干秒，屏幕中央显示「倒计时: MM:SS」（与主实验冷却 HUD 风格一致），
再按 sim_time_s（若无列则 timestamp−首采样）墙钟节拍正常回放。其余逻辑与 tools/replay_trajectory.py 相同；
会话 JSON 的 cycles[] 每段 experiment_start/end 自「该段倒计时结束」起计时；墙钟回放节拍与 L4 一致（优先 sim_time_s）。
每段字段：experiment_start_system_local、experiment_end_system_local、experiment_duration_wall_s
（另含 schema、根目录、sequences、session_id 等元数据）。
默认写入 overtake_root 下：`overtake_replay_session_<上级文件夹名>_<被试文件夹名>_YYYYMMDD_HHMMSS_mmm.json`
（上级目录不可用时仅用被试文件夹名）；可用 --replay-session-log 指定路径。

转向灯音频：读取 phase_segments_summary.csv（默认在 overtake_root 上一级目录），在绝对仿真秒落入
[t_end_following, t_p2_end] 以及 [t_end_left_overtake, ego_pos_y 首次回到 lane-return-y]（默认 -7.6）内循环播放 overtake.mp3（默认同上目录）。
相位表与 driving_data 均为 sim_time_s 时窗口与 CSV 一致；无 sim_time_s 时退化为相对首采样的 timestamp 秒。
两段的 sim 起始再整体提前 `--turn-signal-advance-s`（默认 2.5）秒，结束时刻不变。

用法:
    python replay_trajectory_overtaking.py <overtake_root> [与 replay_trajectory 相同的选项]

示例:
    python replay_trajectory_overtaking.py ../phase2/my_run --snap-to-road
    python replay_trajectory_overtaking.py ../phase2/my_run --csv-name driving_data.csv --hold-first-frame-s 10
    python replay_trajectory_overtaking.py ../phase2/my_run --playback-start-sim-offset-s 0
"""

import argparse
import csv
import glob
import os
import sys
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

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import replay_trajectory as rt


EXP_ORDER = ('exp1_o', 'exp2_o', 'exp3_o')

# 首帧倒计时 HUD 与窗口标题：仅「超车exp1 / 超车exp2 / 超车exp3」，不显示脚本名或数据文件夹名。
OVERTAKE_COUNTDOWN_LABEL = {
    'exp1_o': '超车exp1',
    'exp2_o': '超车exp2',
    'exp3_o': '超车exp3',
}


def _overtake_countdown_label(tag):
    return OVERTAKE_COUNTDOWN_LABEL.get(tag, f'超车{tag}')


def _sanitize_filename_tag(s):
    """目录名用作文件名片段：字母数字与 - _ 保留，其余替换为 _。"""
    if not s:
        return ''
    return ''.join(c if (c.isalnum() or c in '-_') else '_' for c in s)


def _default_overtake_session_log_path(overtake_root):
    """
    默认会话 JSON：<上级文件夹名>_<当前 overtake_root 文件夹名>_时间戳，
    便于归档且与同 phase 下其他被试区分。
    """
    root = os.path.abspath(overtake_root)
    leaf = _sanitize_filename_tag(os.path.basename(root.rstrip(os.sep)))
    parent_dir = os.path.dirname(root)
    parent_leaf = (
        _sanitize_filename_tag(os.path.basename(parent_dir.rstrip(os.sep)))
        if parent_dir
        else ''
    )
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    if parent_leaf and parent_leaf != leaf:
        tag = f'{parent_leaf}_{leaf}'
    else:
        tag = leaf or 'session'
    return os.path.join(root, f'overtake_replay_session_{tag}_{stamp}.json')


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


def load_phase_segments_map(phase_segments_csv_path):
    """file 列已为相对 overtaking phase 根的 POSIX 路径，如 T1/.../driving_data.csv。"""
    m = {}
    with open(phase_segments_csv_path, 'r', encoding='utf-8', newline='') as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            key = (row.get('file') or '').strip().replace('\\', '/')
            if key:
                m[key] = row
    return m


def _csv_rel_under_phase_root(csv_abs_path, phase_root_abs):
    return (
        os.path.normpath(os.path.relpath(csv_abs_path, phase_root_abs)).replace('\\', '/')
    )


def _sim_time_first_lane_return(trajectory, play_start_ts, sim_from_s, lane_y, tol):
    """从 sim≥sim_from_s 起，首次 ego_y 与 lane_y 接近（纵向回到车道）；若始终未满足则退回末帧 sim。"""
    t_end = rt.playback_absolute_sim_s(trajectory[-1], play_start_ts)
    for pt in trajectory:
        sim = rt.playback_absolute_sim_s(pt, play_start_ts)
        if sim < sim_from_s:
            continue
        if abs(float(pt['ego_y']) - float(lane_y)) <= tol:
            return float(sim)
    return float(t_end)


def build_turn_signal_sim_windows(row, trajectory, lane_y, lane_tol, advance_start_s=2.5):
    """
    interval1: [t_end_following, t_p2_end]
    interval2: [t_end_left_overtake, sim when ego_pos_y≈lane_y after left overtake]
    随后在保持结束时刻不变的前提下，将各段起始提前 advance_start_s（秒），下界不小于 0。
    """
    if not row:
        return []
    try:
        t_ef = float(row['t_end_following'])
        t_p2 = float(row['t_p2_end'])
        t_elo = float(row['t_end_left_overtake'])
    except (KeyError, TypeError, ValueError):
        return []
    windows = []
    if t_ef <= t_p2:
        windows.append((t_ef, t_p2))
    play_start_ts = trajectory[0]['timestamp']
    t_lane = _sim_time_first_lane_return(
        trajectory, play_start_ts, t_elo, lane_y, lane_tol
    )
    if t_elo <= t_lane:
        windows.append((float(t_elo), float(t_lane)))
    adv = float(advance_start_s)
    out = []
    for lo, hi in windows:
        nlo = max(0.0, float(lo) - adv)
        if nlo < float(hi):
            out.append((nlo, float(hi)))
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
    mini.add_argument(
        '--playback-end-sim-s',
        type=float,
        default=0.0,
        help='每条 CSV 的 sim 时间上限（秒），0=播放到文件末尾；超车顺序回放默认 0',
    )
    mini.add_argument(
        '--playback-start-sim-offset-s',
        type=float,
        default=3.0,
        help='每条 CSV 从 sim_time≥本值(秒)的首帧起播，默认 3',
    )
    mini.add_argument(
        '--phase-segments-csv',
        default='',
        metavar='PATH',
        help=(
            'phase_segments_summary.csv 路径（含 t_end_following 等列）；'
            '默认 <overtake_root 上一级>/phase_segments_summary.csv'
        ),
    )
    mini.add_argument(
        '--turn-signal-audio',
        default='',
        metavar='PATH',
        help='转向灯/超车提示 mp3；默认 <overtake_root 上一级>/overtake.mp3',
    )
    mini.add_argument(
        '--lane-return-y',
        type=float,
        default=-7.6,
        help='左转超车后 ego_pos_y 回到目标车道侧的判定 y（米），默认 -7.6',
    )
    mini.add_argument(
        '--lane-return-tol',
        type=float,
        default=0.12,
        help='判定「回到 lane-return-y」的半宽容忍（米），默认 0.12',
    )
    mini.add_argument(
        '--no-turn-signal-audio',
        action='store_true',
        help='不根据 phase_segments 播放转向灯音频',
    )
    mini.add_argument(
        '--turn-signal-advance-s',
        type=float,
        default=2.5,
        help='转向灯 sim 窗口起始相对 CSV 相位再提前的秒数，结束不变；默认 2.5',
    )
    mini_args, rest = mini.parse_known_args()

    rt_parser = rt.build_replay_argparser(include_csv_positional=False)
    rt_args = rt_parser.parse_args(rest)

    # 先 rt 再 mini：mini 覆盖同名项（如 --playback-end-sim-s）。合并为单 dict 再 Namespace，
    # 避免 rt/mini 均含 playback_end_sim_s 时 Namespace(**rt, **mini) 触发重复关键字错误。
    _merged = vars(rt_args).copy()
    _merged.update(vars(mini_args))
    args = argparse.Namespace(**_merged)

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

    phase_root = os.path.dirname(os.path.abspath(args.overtake_root))
    segments_map = {}
    turn_mp3_path = None
    if not getattr(args, 'no_turn_signal_audio', False):
        pcs = (args.phase_segments_csv or '').strip().strip('"')
        if not pcs:
            pcs = os.path.join(phase_root, 'phase_segments_summary.csv')
        tpm = (args.turn_signal_audio or '').strip().strip('"')
        if not tpm:
            tpm = os.path.join(phase_root, 'overtake.mp3')
        if os.path.isfile(pcs):
            segments_map = load_phase_segments_map(pcs)
            print(f'已加载相位表: {pcs}（{len(segments_map)} 行）')
        else:
            print(f'相位表未找到，跳过转向灯: {pcs}')
        if os.path.isfile(tpm):
            turn_mp3_path = tpm
            print(f'转向灯音频: {turn_mp3_path}')
        else:
            print(f'转向灯音频文件不存在，跳过: {tpm}')
    lane_y = float(getattr(args, 'lane_return_y', -7.6))
    lane_tol = float(getattr(args, 'lane_return_tol', 0.12))
    turn_adv = float(getattr(args, 'turn_signal_advance_s', 2.5))

    if args.replay_session_log:
        session_log_path = os.path.abspath(args.replay_session_log)
    else:
        session_log_path = os.path.abspath(
            _default_overtake_session_log_path(args.overtake_root)
        )
    print(f'会话记录(JSON): {session_log_path}')
    session_log = {
        'schema_version': 1,
        'kind': 'overtaking_sequence',
        'overtake_root': os.path.abspath(args.overtake_root),
        'replay_session_log': session_log_path,
        'csv_name': args.csv_name,
        'hold_first_frame_s': float(args.hold_first_frame_s),
        'sequences': [{'tag': t, 'csv': c} for t, c in sequences],
        'session_id': None,
        'cycles': [],
    }

    pygame.init()
    pygame.font.init()
    try:
        pygame.mixer.init()
    except pygame.error:
        pass
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
    pygame.display.set_caption('超车')
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

            rel_key = _csv_rel_under_phase_root(csv_path, phase_root)
            row = segments_map.get(rel_key)
            sim_windows = []
            if segments_map and turn_mp3_path and row:
                if (row.get('status') or '').lower() != 'ok':
                    print(f'  [转向灯] CSV 相位行 status≠ok，仍尝试使用: {rel_key}')
                sim_windows = build_turn_signal_sim_windows(
                    row, trajectory, lane_y, lane_tol, advance_start_s=turn_adv
                )
                if sim_windows:
                    print(f'  [转向灯] sim 窗口（秒）: {sim_windows}')
                else:
                    print(f'  [转向灯] 无有效窗口: {rel_key}')
            elif segments_map and not row:
                print(f'  [转向灯] phase_segments_summary 无匹配行: {rel_key}')

            rt.destroy_replay_actors(camera, ego_vehicle, lead_vehicle)
            camera, ego_vehicle, lead_vehicle = None, None, None

            ego_vehicle, lead_vehicle, camera = rt.spawn_replay_vehicles_and_camera(
                world, args, road_z, trajectory, has_lead
            )
            print(f'自车已生成: {ego_vehicle.type_id}')
            if lead_vehicle:
                print(f'前车已生成: {lead_vehicle.type_id}')

            pygame.display.set_caption(_overtake_countdown_label(tag))
            hold_lines = [_overtake_countdown_label(tag)]

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
                playback_start_sim_offset_s=float(args.playback_start_sim_offset_s),
                slim_experiment_session_log=True,
                turn_signal_mp3_path=turn_mp3_path if sim_windows else None,
                turn_signal_sim_windows=sim_windows,
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
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
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
