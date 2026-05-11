#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
轨迹回放工具 - 驾驶者视角回放

在 CARLA 中复现 CSV 记录的跟驰场景，包括自车和前车

用法:
    python replay_trajectory.py <csv_file> [options]

多屏与正常驾驶一致：自车 role_name=hero，侧视/后视等相机脚本会附着同一辆车。
可先启动本脚本再启动 cameras/*.py，或直接使用项目根目录的 launch_replay_all_views.ps1。
加 --snap-to-road 时按地图 waypoint 对齐路面高度（坡道观感更好）；默认对贴地 z 做平滑+限幅。默认关闭车辆物理，减轻每帧 teleport 与悬挂/地面求解冲突导致的相机抖动；需要真实车体动力学时加 --vehicle-physics。默认天气 ClearNoon；可用 --replay-weather 换 CARLA 内置预设（如 WetNoon、ClearSunset）。可加 --replay-sun-overhead-forward 使太阳近天顶（短影）并按自车航向每帧调方位角。主相机 gamma 默认 2.2（见 --gamma）。保留服务器天气请加 --keep-world-weather。

示例:
    python replay_trajectory.py ../experiment_data/20260302_032032/driving_data.csv
    python replay_trajectory.py ../experiment_data/20260302_032032/driving_data.csv --speed 2.0
    python replay_trajectory.py ../experiment_data/20260302_032032/driving_data.csv --res 1920x1080 --display 2
    python replay_trajectory.py data.csv --replay-weather WetNoon
    python replay_trajectory.py data.csv --replay-sun-overhead-forward --replay-sun-yaw-offset-deg 180

回放开始与结束时间会写入与 CSV 同目录的 driving_data_replay_session.json（可用 --replay-session-log 指定）。
JSON 文件头含 session_id（UTC 时间戳 + CSV 主文件名 + L4），便于检索。
"""

import glob
import json
import os
import sys
import argparse
import csv
import time
import math
import weakref
from datetime import datetime, timezone

# 添加CARLA路径
try:
    sys.path.append(glob.glob('../../carla/dist/carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass

import carla
import pygame
import numpy as np


def _default_replay_session_log_path(csv_path):
    d = os.path.dirname(os.path.abspath(csv_path))
    base = os.path.basename(csv_path)
    root, _ = os.path.splitext(base)
    return os.path.join(d, f'{root}_replay_session.json')


def _write_replay_session_log(path, data):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def make_session_filter_id(utc_dt, csv_path, mode_tag):
    """
    UTC 时间戳 + CSV 主文件名 + 模式标签，写入 JSON 文件头 session_id，
    便于按时间或数据源筛选（与 experiment_start_utc 同源时刻）。
    """
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    ts = utc_dt.strftime('%Y%m%d_%H%M%S_%f')[:-3]
    return f'{ts}_{stem}_{mode_tag}'


def find_chinese_font():
    """与 car_following_experiment.HUD 一致：查找支持中文的字体路径。"""
    chinese_font_names = [
        'notosanscjk', 'notosanssc', 'notosanstc', 'notosanshk',
        'wenquanyimicrohei', 'wenquanyizenhei', 'wenquanyi',
        'droidsansfallback', 'droidsans',
        'microsoftyahei', 'yahei', 'simhei', 'simsun',
        'arialuni', 'arial unicode',
        'dejavusans', 'freesans', 'liberation',
    ]
    available_fonts = pygame.font.get_fonts()
    for font_name in chinese_font_names:
        for available in available_fonts:
            if font_name in available.lower().replace(' ', '').replace('-', ''):
                font_path = pygame.font.match_font(available)
                if font_path:
                    return font_path
    font_paths = [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/wenquanyi/wqy-microhei/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for path in font_paths:
        if os.path.exists(path):
            return path
    return None


def make_replay_hud_fonts():
    """
    与 car_following_experiment.HUD._init_fonts 对齐：
    小号正文 14px，速度行数值 14*4=56px。
    """
    path = find_chinese_font()
    if path:
        print(f"回放 HUD 字体: {os.path.basename(path)}")
        mono = pygame.font.Font(path, 14)
        mono_speed = pygame.font.Font(path, 14 * 4)
        mono_title = pygame.font.Font(path, 16)
    else:
        print('回放 HUD: 未找到中文字体，使用等宽/默认字体')
        font_name = 'courier' if os.name == 'nt' else 'mono'
        fonts = [x for x in pygame.font.get_fonts() if font_name in x]
        default_font = 'ubuntumono'
        mono_key = default_font if default_font in fonts else (fonts[0] if fonts else None)
        mpath = pygame.font.match_font(mono_key) if mono_key else None
        mono = pygame.font.Font(mpath, 14) if mpath else pygame.font.Font(None, 14)
        mono_speed = pygame.font.Font(mpath, 14 * 4) if mpath else pygame.font.Font(None, 14 * 4)
        mono_title = pygame.font.Font(mpath, 16) if mpath else pygame.font.Font(None, 16)
    return mono, mono_speed, mono_title


def _hud_split_suffix(item, suffix):
    if item.endswith(suffix):
        return item[: -len(suffix)], suffix
    return None, None


def _blit_value_unit_line(display, x, y, main_part, unit_part, font_mono, font_big, color, unit_color):
    """大号主文 + 小号单位（与主实验 HUD 速度行一致）。"""
    main_s = font_big.render(main_part, True, color)
    unit_s = font_mono.render(unit_part, True, unit_color)
    uy = y + main_s.get_height() - unit_s.get_height()
    display.blit(main_s, (x, y))
    display.blit(unit_s, (x + main_s.get_width(), uy))
    return main_s.get_height() + 10


class DriverCamera:
    """驾驶者视角摄像机：与 car_following_experiment.CameraManager 首视角（Rigid + x=0.5,z=1.4,fov=90）一致。"""
    
    def __init__(self, world, vehicle, width=1280, height=720, gamma=2.2):
        self.surface = None
        self.vehicle = vehicle
        
        bp_library = world.get_blueprint_library()
        camera_bp = bp_library.find('sensor.camera.rgb')
        camera_bp.set_attribute('image_size_x', str(width))
        camera_bp.set_attribute('image_size_y', str(height))
        camera_bp.set_attribute('fov', '90')
        if camera_bp.has_attribute('gamma'):
            camera_bp.set_attribute('gamma', str(gamma))
        if camera_bp.has_attribute('motion_blur_intensity'):
            camera_bp.set_attribute('motion_blur_intensity', '0')
        
        # 驾驶者视角位置 - 与主脚本 car_following_experiment.py 一致
        # 位于车辆前部中央，高度1.4m，不会看到方向盘
        camera_transform = carla.Transform(
            carla.Location(x=0.5, z=1.4),  # 与主脚本一致
            carla.Rotation()  # 无旋转，水平视角
        )
        
        self.camera = world.spawn_actor(
            camera_bp,
            camera_transform,
            attach_to=vehicle,
            attachment_type=carla.AttachmentType.Rigid,
        )
        
        weak_self = weakref.ref(self)
        self.camera.listen(lambda image: DriverCamera._parse_image(weak_self, image))
        
    @staticmethod
    def _parse_image(weak_self, image):
        self = weak_self()
        if not self:
            return
        array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
        array = np.reshape(array, (image.height, image.width, 4))
        array = array[:, :, :3]
        array = array[:, :, ::-1]
        self.surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
        
    def render(self, display):
        if self.surface is not None:
            display.blit(self.surface, (0, 0))
            
    def destroy(self):
        if self.camera:
            self.camera.stop()
            self.camera.destroy()


def load_trajectory(csv_file):
    """加载CSV轨迹数据"""
    trajectory = []
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        
        for row in reader:
            point = {
                'timestamp': float(row['timestamp']),
                'ego_x': float(row['ego_pos_x']),
                'ego_y': float(row['ego_pos_y']),
                'ego_speed': float(row['ego_speed']),
                'ego_yaw': float(row.get('ego_yaw', 0)) if 'ego_yaw' in row else None,
            }
            
            # 前车数据
            if 'lead_pos_x' in row and row['lead_pos_x']:
                point['lead_x'] = float(row['lead_pos_x'])
                point['lead_y'] = float(row['lead_pos_y'])
                point['lead_yaw'] = float(row.get('lead_yaw', 0)) if 'lead_yaw' in row else None
                point['lead_speed'] = float(row.get('lead_speed', 0))
            else:
                # 旧数据：根据距离估算前车位置
                if 'distance_headway' in row and row['distance_headway'] and point['ego_yaw'] is not None:
                    dist = float(row['distance_headway'])
                    rad = math.radians(point['ego_yaw'])
                    point['lead_x'] = point['ego_x'] + dist * math.cos(rad)
                    point['lead_y'] = point['ego_y'] + dist * math.sin(rad)
                    point['lead_yaw'] = point['ego_yaw']
                    point['lead_speed'] = float(row.get('lead_speed', 0))
                else:
                    point['lead_x'] = None
                    point['lead_y'] = None
                    point['lead_yaw'] = None
                    point['lead_speed'] = 0

            # 车间距（米）：优先 CSV；否则用平面几何中心距近似
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

            trajectory.append(point)
            
    return trajectory


def estimate_yaw(trajectory):
    """根据位置变化估算朝向（如果没有记录yaw）"""
    for i in range(len(trajectory) - 1):
        if trajectory[i]['ego_yaw'] is None:
            dx = trajectory[i+1]['ego_x'] - trajectory[i]['ego_x']
            dy = trajectory[i+1]['ego_y'] - trajectory[i]['ego_y']
            if abs(dx) > 0.01 or abs(dy) > 0.01:
                trajectory[i]['ego_yaw'] = math.degrees(math.atan2(dy, dx))
            else:
                trajectory[i]['ego_yaw'] = trajectory[i-1]['ego_yaw'] if i > 0 else 0
                
        if trajectory[i]['lead_yaw'] is None and trajectory[i]['lead_x'] is not None:
            # 简单假设前车朝向与自车相同
            trajectory[i]['lead_yaw'] = trajectory[i]['ego_yaw']
            
    # 最后一个点
    if trajectory:
        if trajectory[-1]['ego_yaw'] is None:
            trajectory[-1]['ego_yaw'] = trajectory[-2]['ego_yaw'] if len(trajectory) > 1 else 0
        if trajectory[-1]['lead_yaw'] is None and trajectory[-1]['lead_x'] is not None:
            trajectory[-1]['lead_yaw'] = trajectory[-1]['ego_yaw']
            
    return trajectory


def _stabilize_kinematic_vehicle_visuals(vehicle):
    """
    关闭物理时每帧 teleport 时，轮毂/制动灯等仍可能按内部状态更新，易产生高光与局部光照闪烁。
    用中性控制 + 关灯压低帧间差异（CARLA 版本若不支持会静默跳过）。
    """
    try:
        vehicle.apply_control(carla.VehicleControl())
    except Exception:
        pass
    try:
        vehicle.set_light_state(carla.VehicleLightState.NONE)
    except Exception:
        pass


def list_weather_preset_names():
    """CARLA WeatherParameters 上常见的预设名（首字母大写的属性）。"""
    return sorted(
        n for n in dir(carla.WeatherParameters)
        if n and n[0].isupper() and not n.startswith('_')
    )


def apply_replay_weather(world, preset_name):
    """
    按预设名设置天气，例如 ClearNoon、WetNoon、CloudySunset。
    preset_name 须为 carla.WeatherParameters 上的属性名。
    """
    try:
        preset = getattr(carla.WeatherParameters, str(preset_name), None)
        if preset is None:
            return False
        world.set_weather(preset)
        return True
    except Exception:
        return False


def sync_replay_sun(world, altitude_deg, ego_yaw_deg, azimuth_offset_deg=0.0):
    """
    在保留当前云量等参数的前提下，只调太阳高度角与方位角。

    - 太阳高度角接近 90°（天顶）时，地面与竖直物体影子极短，侧向长影明显减少。
    - 方位角按自车 yaw 对齐（+ offset），便于让车头朝向一侧更偏受光；CARLA/Unreal 与
      车辆 yaw 的对应因版本可能有偏差，需用 --replay-sun-yaw-offset-deg 微调（可试 90 或 180）。
    """
    altitude_deg = max(0.0, min(90.0, float(altitude_deg)))
    try:
        w = world.get_weather()
        if hasattr(w, 'sun_altitude_angle'):
            w.sun_altitude_angle = altitude_deg
        if hasattr(w, 'sun_azimuth_angle'):
            yaw = float(ego_yaw_deg) if ego_yaw_deg is not None else 0.0
            w.sun_azimuth_angle = (yaw + float(azimuth_offset_deg)) % 360.0
        world.set_weather(w)
    except Exception:
        pass


def make_road_z_resolver(world, enabled, z_offset, fallback_z=0.5):
    """
    若 enabled：用地图 waypoint 将 (x,y) 投影到可行驶车道，返回路面高度 + z_offset。
    否则恒返回 fallback_z（与旧版固定高度一致）。
    """
    if not enabled:
        return lambda _x, _y: fallback_z

    carla_map = world.get_map()

    def road_z(x, y):
        # 较高 z 便于 project_to_road 从上方命中路面（桥梁/坡道）
        loc = carla.Location(x=float(x), y=float(y), z=500.0)
        wp = None
        try:
            wp = carla_map.get_waypoint(
                loc, project_to_road=True, lane_type=carla.LaneType.Driving
            )
        except Exception:
            wp = None
        if wp is None:
            try:
                wp = carla_map.get_waypoint(loc, project_to_road=True)
            except Exception:
                wp = None
        if wp is None:
            return fallback_z
        return wp.transform.location.z + z_offset

    return road_z


class ZSmoother:
    """对路面采样 z 做指数平滑，减轻 get_waypoint 在车道/路段边界处的帧间跳变。"""

    def __init__(self, alpha, max_step_m=0.0):
        self.alpha = float(alpha)
        self.max_step_m = float(max_step_m)
        self._z = None

    def reset(self):
        self._z = None

    def smooth(self, z_raw):
        prev = self._z
        if prev is None:
            self._z = z_raw
        else:
            blended = self.alpha * z_raw + (1.0 - self.alpha) * prev
            if self.max_step_m > 0:
                lo, hi = prev - self.max_step_m, prev + self.max_step_m
                blended = min(hi, max(lo, blended))
            self._z = blended
        return self._z


def draw_hud(display, point, display_size, font_mono, font_mono_speed, font_title):
    """参考主实验 HUD：左侧半透明信息栏（标题中字、标签中字、数字大字、单位小字）。"""
    _dw, dh = display_size
    info_surface = pygame.Surface((420, dh))
    info_surface.set_alpha(100)
    display.blit(info_surface, (0, 0))

    ego_kmh = point['ego_speed'] * 3.6
    if point.get('lead_x') is not None:
        lead_kmh = point.get('lead_speed', 0.0) * 3.6
        dist = point.get('distance_headway')
        lead_value = f"{lead_kmh:.0f}"
        dist_value = f"{dist:.1f}" if dist is not None else "--"
    else:
        lead_value = "--"
        dist_value = "--"

    title = '--- 行车信息 ---'
    title_s = font_title.render(title, True, (255, 255, 255))
    display.blit(title_s, (max(8, (420 - title_s.get_width()) // 2), 14))

    def draw_metric_line(y, label, value, unit):
        """标签(中字)、数值(大字)、单位(小字)共用同一文本基线。"""
        label_s = font_title.render(f"{label}:", True, (255, 255, 255))
        value_x = 8 + label_s.get_width() + 10

        if value == "--":
            value_s = font_title.render(value, True, (255, 255, 255))
            fonts_row = (font_title, font_title)
            surfaces = (label_s, value_s)
            xs = (8, value_x)
        else:
            value_s = font_mono_speed.render(value, True, (255, 255, 255))
            unit_s = font_mono.render(unit, True, (255, 255, 255))
            fonts_row = (font_title, font_mono_speed, font_mono)
            surfaces = (label_s, value_s, unit_s)
            xs = (8, value_x, value_x + value_s.get_width() + 4)

        baseline_y = y + max(f.get_ascent() for f in fonts_row)
        for surf, font, x in zip(surfaces, fonts_row, xs):
            display.blit(surf, (x, baseline_y - font.get_ascent()))
        d_max = max(f.get_descent() for f in fonts_row)
        return (baseline_y + d_max) - y + 8

    v_offset = 44
    v_offset += draw_metric_line(v_offset, "自车", f"{ego_kmh:.0f}", "km/h")
    v_offset += draw_metric_line(v_offset, "前车", lead_value, "km/h")
    draw_metric_line(v_offset, "车头间距", dist_value, "m")


def main():
    argparser = argparse.ArgumentParser(description='轨迹回放工具 - 驾驶者视角')
    argparser.add_argument('csv_file', help='CSV数据文件路径')
    argparser.add_argument('--host', default='127.0.0.1', help='CARLA服务器IP')
    argparser.add_argument('-p', '--port', default=2000, type=int, help='CARLA服务器端口')
    argparser.add_argument('--speed', default=1.0, type=float, help='回放速度倍率 (默认1.0)')
    argparser.add_argument('--seek-step-pct', default=1.0, type=float,
                          help='进度跳转步长(占总帧百分比)。默认1%%，按←/→时生效')
    argparser.add_argument('--seek-big-step-pct', default=10.0, type=float,
                          help='进度大步跳转(占总帧百分比)。默认10%%，按PgUp/PgDn时生效')
    argparser.add_argument('--ego-vehicle', default='vehicle.audi.tt', help='自车蓝图')
    argparser.add_argument('--lead-vehicle', default='vehicle.tesla.model3', help='前车蓝图')
    argparser.add_argument('--loop', action='store_true', help='循环回放')
    argparser.add_argument('--res', default=None,
                          help='窗口分辨率 WxH（与主实验一致），指定时覆盖 --width/--height')
    argparser.add_argument('--width', default=1280, type=int, help='窗口宽度')
    argparser.add_argument('--height', default=720, type=int, help='窗口高度')
    argparser.add_argument('--display', default=0, type=int, help='显示器编号 (0,1,2…)，与 launch_all_views 多屏一致')
    argparser.add_argument('--fullscreen', action='store_true', help='全屏（主实验同款）')
    argparser.add_argument('--no-lead', action='store_true', help='不显示前车')
    argparser.add_argument(
        '--snap-to-road',
        action='store_true',
        help='用 get_map().get_waypoint 将自车/前车 z 贴到路面（推荐有坡或桥时开启）',
    )
    argparser.add_argument(
        '--snap-z-offset',
        default=0.12,
        type=float,
        help='贴地后在路面高度上再抬高(米)，补偿车体原点与地面的间隙，默认 0.12',
    )
    argparser.add_argument(
        '--lead-z-offset',
        default=-0.07,
        type=float,
        help='仅前车：在贴地 z 上再叠加的偏移(米)，负值略压低、减轻漂浮感；默认 -0.06',
    )
    argparser.add_argument(
        '--no-z-smooth',
        action='store_true',
        help='关闭 z 指数平滑（默认开启；仅在与 --snap-to-road 一起用时有效）',
    )
    argparser.add_argument(
        '--z-smooth-alpha',
        default=0.2,
        type=float,
        help='z 平滑系数 0~1，越大越跟原始贴地高度、抖动可能更明显；越小越稳但略有滞后，默认 0.2',
    )
    argparser.add_argument(
        '--z-smooth-max-step',
        default=0.06,
        type=float,
        help='与 --snap-to-road 联用时，每帧平滑后 z 相对上一帧最大变化(米)，抑制尖峰；0 表示不限幅，默认 0.06',
    )
    argparser.add_argument(
        '--vehicle-physics',
        action='store_true',
        help='保留车辆物理模拟。默认关闭：每帧 set_transform 时物理/悬挂易与贴地 z 打架导致画面抖动',
    )
    argparser.add_argument(
        '--keep-world-weather',
        action='store_true',
        help='不修改天气。默认否则套用 --replay-weather（默认 ClearNoon）',
    )
    argparser.add_argument(
        '--replay-weather',
        default='ClearNoon',
        metavar='NAME',
        help=(
            '回放开始时天气预设名（carla.WeatherParameters 属性），默认 ClearNoon。'
            '常见正午: ClearNoon, CloudyNoon, WetNoon, WetCloudyNoon, SoftRainNoon, MidRainyNoon, HardRainNoon；'
            '黄昏: ClearSunset, CloudySunset, WetSunset, WetCloudySunset, SoftRainSunset, MidRainSunset, HardRainSunset'
        ),
    )
    argparser.add_argument(
        '--replay-sun-overhead-forward',
        action='store_true',
        help=(
            '太阳近于天顶（短影）并按自车航向每帧调方位角，使前行方向更偏受光；'
            '需未使用 --keep-world-weather。无法完全关闭引擎阴影，仅尽量减弱侧向长影'
        ),
    )
    argparser.add_argument(
        '--replay-sun-altitude-deg',
        default=89.0,
        type=float,
        help='与 --replay-sun-overhead-forward 联用：太阳高度角 0~90，默认 89（近天顶）',
    )
    argparser.add_argument(
        '--replay-sun-yaw-offset-deg',
        default=0.0,
        type=float,
        help='方位角 = 自车 yaw + 本偏移；光影方向反了可试 180 或 ±90',
    )
    argparser.add_argument(
        '--gamma',
        default=2.2,
        type=float,
        help='主视角 RGB 相机 gamma，与 car_following_experiment.py --gamma 一致；默认 2.2',
    )
    argparser.add_argument(
        '--replay-session-log',
        default=None,
        metavar='PATH',
        help='记录回放开始/结束时间的 JSON；默认与 CSV 同目录 <stem>_replay_session.json',
    )
    args = argparser.parse_args()

    if args.res:
        try:
            args.width, args.height = [int(x) for x in args.res.split('x')]
        except ValueError:
            argparser.error('--res 格式应为 WxH，例如 1920x1080')
    if args.gamma <= 0:
        argparser.error('--gamma 应为正数')
    if args.replay_sun_overhead_forward and args.keep_world_weather:
        argparser.error('--replay-sun-overhead-forward 与 --keep-world-weather 不能同时使用')
    if args.replay_sun_altitude_deg < 0 or args.replay_sun_altitude_deg > 90:
        argparser.error('--replay-sun-altitude-deg 应在 0~90')
    if (
        not args.keep_world_weather
        and getattr(carla.WeatherParameters, args.replay_weather, None) is None
    ):
        avail = list_weather_preset_names()
        preview = ', '.join(avail[:24])
        more = f' … 共 {len(avail)} 个' if len(avail) > 24 else ''
        argparser.error(
            f'--replay-weather 无效: {args.replay_weather!r}。'
            f' 可用预设示例: {preview}{more}'
        )
    
    # 加载轨迹
    print(f"加载轨迹: {args.csv_file}")
    trajectory = load_trajectory(args.csv_file)
    print(f"轨迹点数: {len(trajectory)}")
    
    if not trajectory:
        print("错误: 轨迹为空")
        return
    
    # 估算缺失的朝向
    trajectory = estimate_yaw(trajectory)
    
    # 检查是否有前车数据
    has_lead = trajectory[0].get('lead_x') is not None and not args.no_lead
    print(f"前车数据: {'有' if has_lead else '无'}")

    session_log_path = os.path.abspath(
        args.replay_session_log or _default_replay_session_log_path(args.csv_file)
    )
    session_log = {
        'schema_version': 1,
        'session_id': None,
        'replay_session_log': session_log_path,
        'csv_file': os.path.abspath(args.csv_file),
        'trajectory_first_timestamp': trajectory[0]['timestamp'],
        'speed_at_launch': float(args.speed),
        'loop': bool(args.loop),
        'playback_cycle_index': None,
        'experiment_start_utc': None,
        'experiment_start_monotonic_s': None,
        'experiment_start_wall_time_s': None,
        'cycles': [],
        'session_end_utc': None,
    }

    # 初始化Pygame
    pygame.init()
    pygame.font.init()
    font_mono, font_mono_speed, font_title = make_replay_hud_fonts()

    display_flags = pygame.HWSURFACE | pygame.DOUBLEBUF
    if args.fullscreen:
        display_flags |= pygame.FULLSCREEN
    display = pygame.display.set_mode(
        (args.width, args.height),
        display_flags,
        display=args.display,
    )
    pygame.display.set_caption('轨迹回放 - 驾驶者视角')
    clock = pygame.time.Clock()
    
    # 连接CARLA
    client = carla.Client(args.host, args.port)
    client.set_timeout(10.0)
    world = client.get_world()
    
    # 设置同步模式
    settings = world.get_settings()
    original_settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)

    if not args.keep_world_weather:
        if apply_replay_weather(world, args.replay_weather):
            print(f'回放: 天气预设 {args.replay_weather}')
        else:
            print('回放: 设置天气失败，保持服务器天气')

    road_z = make_road_z_resolver(
        world,
        args.snap_to_road,
        args.snap_z_offset,
        fallback_z=0.5,
    )
    use_z_smooth = args.snap_to_road and not args.no_z_smooth
    if args.z_smooth_alpha <= 0 or args.z_smooth_alpha > 1:
        argparser.error('--z-smooth-alpha 应在 (0, 1] 内')
    if args.z_smooth_max_step < 0:
        argparser.error('--z-smooth-max-step 不能为负')
    z_max_step = args.z_smooth_max_step if use_z_smooth else 0.0
    ego_z_smoother = ZSmoother(args.z_smooth_alpha, max_step_m=z_max_step)
    lead_z_smoother = ZSmoother(args.z_smooth_alpha, max_step_m=z_max_step)
    last_applied_idx = None

    if args.snap_to_road:
        print('贴地回放: 已启用 --snap-to-road (waypoint 对齐 z)')
        if use_z_smooth:
            ms = args.z_smooth_max_step
            ms_txt = f'每帧限幅 ±{ms}m' if ms > 0 else '无限幅'
            print(f'z 平滑: EMA alpha={args.z_smooth_alpha}, {ms_txt}（--no-z-smooth 可关）')

    # 清掉场景中同名 role 的旧车，避免多 hero / 相机绑到上一段回放的车辆（侧视颜色与切换异常）
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
    
    # 生成车辆
    bp_library = world.get_blueprint_library()
    
    # 自车 - 与主实验脚本一致
    ego_bp = bp_library.find(args.ego_vehicle)
    ego_bp.set_attribute('role_name', 'hero')
    # 与 car_following_experiment.py 一致：白色车漆（Audi TT 等在车身上呈浅银观感）
    if ego_bp.has_attribute('color'):
        ego_bp.set_attribute('color', '255,255,255')
    
    start = trajectory[0]
    z0_ego = road_z(start['ego_x'], start['ego_y'])
    ego_spawn = carla.Transform(
        carla.Location(x=start['ego_x'], y=start['ego_y'], z=z0_ego),
        carla.Rotation(yaw=start['ego_yaw'] if start['ego_yaw'] else 0)
    )
    ego_vehicle = world.spawn_actor(ego_bp, ego_spawn)
    print(f"自车已生成: {ego_vehicle.type_id}")
    
    # 前车 - 与主实验脚本一致 (Tesla Model 3, 蓝色)
    lead_vehicle = None
    if has_lead:
        lead_bp = bp_library.find(args.lead_vehicle)
        lead_bp.set_attribute('role_name', 'lead_vehicle')
        if lead_bp.has_attribute('color'):
            lead_bp.set_attribute('color', '0,0,255')  # 蓝色，与主脚本一致
        z0_lead = road_z(start['lead_x'], start['lead_y']) + args.lead_z_offset
        lead_spawn = carla.Transform(
            carla.Location(x=start['lead_x'], y=start['lead_y'], z=z0_lead),
            carla.Rotation(yaw=start['lead_yaw'] if start['lead_yaw'] else 0)
        )
        lead_vehicle = world.spawn_actor(lead_bp, lead_spawn)
        print(f"前车已生成: {lead_vehicle.type_id}")

    # 轨迹回放每帧 teleport：开着物理时悬挂/地面穿透会与 set_transform 打架，相机绑在车上会明显上下抖
    if not args.vehicle_physics:
        for v in (ego_vehicle, lead_vehicle):
            if v is None:
                continue
            try:
                v.set_simulate_physics(False)
            except Exception:
                pass
        print('回放: 已关闭自车/前车物理（默认，减轻抖动）；需要真实车体动力学请加 --vehicle-physics')
    
    # 创建驾驶者视角摄像机
    camera = DriverCamera(
        world, ego_vehicle, args.width, args.height, gamma=args.gamma
    )
    
    # 等待初始化
    for _ in range(10):
        world.tick()
    
    print(f"\n开始回放 (速度: {args.speed}x)")
    print("按 ESC 退出, 空格键 暂停/继续, +/- 调整速度")
    print("按 ←/→ 调整进度(默认1%%)，按 PgUp/PgDn 快速跳转(默认10%%)")
    print(f'会话记录(JSON): {session_log_path}')

    try:
        running = True
        paused = False
        speed_mult = args.speed
        playback_cycle_index = 0

        play_start_ts = trajectory[0]['timestamp']

        sun_tune = bool(args.replay_sun_overhead_forward)
        sun_alt = float(args.replay_sun_altitude_deg)
        sun_yaw_off = float(args.replay_sun_yaw_offset_deg)

        def maybe_replay_sun(i):
            if not sun_tune:
                return
            pt = trajectory[i]
            y = pt.get('ego_yaw')
            sync_replay_sun(world, sun_alt, y if y is not None else 0.0, sun_yaw_off)

        if sun_tune:
            print(
                f'回放: 太阳高度 {sun_alt}°（近天顶、短影）+ 方位角随自车 yaw，偏移 {sun_yaw_off}°'
            )

        while running:
            wall_start = time.time()
            frame_idx = 0
            exp_start_m = time.monotonic()
            exp_wall_s = time.time()
            now_utc = datetime.now(timezone.utc)
            exp_start_utc = now_utc.isoformat()
            if playback_cycle_index == 0:
                sid = make_session_filter_id(now_utc, args.csv_file, 'L4')
                session_log['session_id'] = sid
                print('')
                print('========== 会话标识（检索用 / JSON 字段 session_id）==========')
                print(f'  session_id:           {sid}')
                print(f'  experiment_start_utc: {exp_start_utc}')
                print('==============================================================')
                print('')
            cycle_rec = {
                'playback_cycle_index': playback_cycle_index,
                'experiment_start_utc': exp_start_utc,
                'experiment_start_monotonic_s': exp_start_m,
                'experiment_start_wall_time_s': exp_wall_s,
            }
            session_log['cycles'].append(cycle_rec)
            session_log['playback_cycle_index'] = playback_cycle_index
            session_log['experiment_start_utc'] = exp_start_utc
            session_log['experiment_start_monotonic_s'] = exp_start_m
            session_log['experiment_start_wall_time_s'] = exp_wall_s
            _write_replay_session_log(session_log_path, session_log)
            seek_step_frames = max(1, int(len(trajectory) * (args.seek_step_pct / 100.0)))
            seek_big_step_frames = max(1, int(len(trajectory) * (args.seek_big_step_pct / 100.0)))

            def apply_frame(idx):
                """将 CSV 中 idx 对应的帧状态应用到 CARLA 实体（不包含 world.tick）。"""
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

                # 自车变换
                ego_transform = carla.Transform(
                    carla.Location(x=p['ego_x'], y=p['ego_y'], z=z_ego),
                    carla.Rotation(yaw=p['ego_yaw'] if p['ego_yaw'] else 0)
                )
                ego_vehicle.set_transform(ego_transform)
                if not args.vehicle_physics:
                    _stabilize_kinematic_vehicle_visuals(ego_vehicle)

                # 仅在开启车辆物理时设速度；运动学模式下由 transform 完全决定位姿，避免与物理求解冲突
                if args.vehicle_physics and p['ego_speed'] > 0 and p['ego_yaw'] is not None:
                    rad = math.radians(p['ego_yaw'])
                    ego_velocity = carla.Vector3D(
                        x=p['ego_speed'] * math.cos(rad),
                        y=p['ego_speed'] * math.sin(rad),
                        z=0
                    )
                    ego_vehicle.set_target_velocity(ego_velocity)

                # 前车变换与速度
                if lead_vehicle and p.get('lead_x') is not None:
                    if use_z_smooth:
                        z_lead = lead_z_smoother.smooth(road_z(p['lead_x'], p['lead_y'])) + args.lead_z_offset
                    else:
                        z_lead = road_z(p['lead_x'], p['lead_y']) + args.lead_z_offset
                    lead_transform = carla.Transform(
                        carla.Location(x=p['lead_x'], y=p['lead_y'], z=z_lead),
                        carla.Rotation(yaw=p['lead_yaw'] if p.get('lead_yaw') else 0)
                    )
                    lead_vehicle.set_transform(lead_transform)
                    if not args.vehicle_physics:
                        _stabilize_kinematic_vehicle_visuals(lead_vehicle)

                    lead_speed = p.get('lead_speed', 0)
                    if args.vehicle_physics and lead_speed > 0 and p.get('lead_yaw') is not None:
                        rad = math.radians(p['lead_yaw'])
                        lead_velocity = carla.Vector3D(
                            x=lead_speed * math.cos(rad),
                            y=lead_speed * math.sin(rad),
                            z=0
                        )
                        lead_vehicle.set_target_velocity(lead_velocity)

                maybe_replay_sun(idx)
            
            while frame_idx < len(trajectory) and running:
                # 事件处理
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            running = False
                        elif event.key == pygame.K_SPACE:
                            paused = not paused
                            print("暂停" if paused else "继续")
                            if not paused:
                                # 维持“暂停=冻结时间”的体验：对齐当前帧的目标时间
                                cur = trajectory[frame_idx]
                                cur_sim = cur['timestamp'] - play_start_ts
                                wall_start = time.time() - (cur_sim / speed_mult)
                        elif event.key == pygame.K_EQUALS or event.key == pygame.K_PLUS:
                            speed_mult = min(10.0, speed_mult + 0.5)
                            print(f"速度: {speed_mult}x")
                            # 对齐当前帧时间，避免改速后跳帧
                            cur = trajectory[frame_idx]
                            cur_sim = cur['timestamp'] - play_start_ts
                            wall_start = time.time() - (cur_sim / speed_mult)
                        elif event.key == pygame.K_MINUS:
                            speed_mult = max(0.1, speed_mult - 0.5)
                            print(f"速度: {speed_mult}x")
                            cur = trajectory[frame_idx]
                            cur_sim = cur['timestamp'] - play_start_ts
                            wall_start = time.time() - (cur_sim / speed_mult)
                        elif event.key == pygame.K_RIGHT:
                            new_idx = min(len(trajectory) - 1, frame_idx + seek_step_frames)
                            if new_idx != frame_idx:
                                frame_idx = new_idx
                                cur_sim = trajectory[frame_idx]['timestamp'] - play_start_ts
                                wall_start = time.time() - (cur_sim / speed_mult)
                                print(f"Seek: {frame_idx + 1}/{len(trajectory)}")
                                if paused:
                                    apply_frame(frame_idx)
                                    world.tick()
                        elif event.key == pygame.K_LEFT:
                            new_idx = max(0, frame_idx - seek_step_frames)
                            if new_idx != frame_idx:
                                frame_idx = new_idx
                                cur_sim = trajectory[frame_idx]['timestamp'] - play_start_ts
                                wall_start = time.time() - (cur_sim / speed_mult)
                                print(f"Seek: {frame_idx + 1}/{len(trajectory)}")
                                if paused:
                                    apply_frame(frame_idx)
                                    world.tick()
                        elif event.key == pygame.K_PAGEUP:
                            new_idx = min(len(trajectory) - 1, frame_idx + seek_big_step_frames)
                            if new_idx != frame_idx:
                                frame_idx = new_idx
                                cur_sim = trajectory[frame_idx]['timestamp'] - play_start_ts
                                wall_start = time.time() - (cur_sim / speed_mult)
                                print(f"Seek: {frame_idx + 1}/{len(trajectory)}")
                                if paused:
                                    apply_frame(frame_idx)
                                    world.tick()
                        elif event.key == pygame.K_PAGEDOWN:
                            new_idx = max(0, frame_idx - seek_big_step_frames)
                            if new_idx != frame_idx:
                                frame_idx = new_idx
                                cur_sim = trajectory[frame_idx]['timestamp'] - play_start_ts
                                wall_start = time.time() - (cur_sim / speed_mult)
                                print(f"Seek: {frame_idx + 1}/{len(trajectory)}")
                                if paused:
                                    apply_frame(frame_idx)
                                    world.tick()
                
                if paused:
                    # 同步模式下其它窗口 wait_for_tick：暂停也必须 tick，否则会全局卡住
                    apply_frame(frame_idx)
                    world.tick()
                    camera.render(display)
                    draw_hud(
                        display,
                        trajectory[frame_idx],
                        display.get_size(),
                        font_mono,
                        font_mono_speed,
                        font_title,
                    )
                    pygame.display.flip()
                    clock.tick(30)
                    continue
                
                point = trajectory[frame_idx]
                
                # 计算目标时间：CSV 时间戳间隔大时，不能长时间只 sleep 不 tick，
                # 否则同步模式下侧视等进程卡在 wait_for_tick。
                sim_time = point['timestamp'] - play_start_ts
                target_time = sim_time / speed_mult
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

                # 更新自车/前车状态（由 CSV 驱动）
                apply_frame(frame_idx)
                
                # 更新世界
                world.tick()
                
                # 渲染
                camera.render(display)
                draw_hud(
                    display,
                    point,
                    display.get_size(),
                    font_mono,
                    font_mono_speed,
                    font_title,
                )
                pygame.display.flip()
                
                clock.tick(60)
                frame_idx += 1
            
            if not args.loop:
                print("\n回放完成")
                # 等待用户按键退出
                while running:
                    world.tick()
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                            running = False
                    clock.tick(30)
            else:
                print("\n循环回放...")
                playback_cycle_index += 1

    except KeyboardInterrupt:
        print("\n用户中断")

    finally:
        session_log['session_end_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            _write_replay_session_log(session_log_path, session_log)
        except Exception:
            pass
        # 恢复设置
        world.apply_settings(original_settings)
        
        # 清理
        camera.destroy()
        ego_vehicle.destroy()
        if lead_vehicle:
            lead_vehicle.destroy()
        pygame.quit()
        print("资源已清理")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n错误: {e}")
