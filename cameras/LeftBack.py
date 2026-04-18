#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
左后视镜相机 - 独立脚本
Left Rearview Mirror Camera

用法:
    python LeftBack.py [--display 1] [--width 384] [--height 216]
    
需要先运行主脚本 car_following_experiment.py 生成车辆
"""

import glob
import os
import sys
import argparse
import ctypes
from ctypes import wintypes

# 添加CARLA路径
try:
    sys.path.append(glob.glob('../../carla/dist/carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass

import carla
import numpy as np
import pygame
import time

# 相机配置
CAMERA_CONFIG = {
    'name': 'Left Rearview Mirror',
    # 当前窗口固定为 250x200，镜面比例同步为 1.25 以避免缩放伪影
    'width': 300,
    'height': 260,
    'fov': 100,
    'mirror_aspect': 1.25,
    # 相机内部采样分辨率（必须为 4 的倍数，宽度不是 4 的倍数会出现斜条纹）
    'sensor_width': 512,
    'sensor_height': 400,
    # 相机位置：左后视镜视角
    'location': carla.Location(x=0.4, y=-1, z=1.1),
    'rotation': carla.Rotation(pitch=-3, yaw=160),
    'flip': True,  # 后视镜需要翻转
    # 梯形遮罩: 4 个角点，按顺序 [左上, 右上, 右下, 左下]，数值为占窗口 (宽, 高) 的比例 0~1
    # 默认模拟左后视镜外窄内宽的轮廓；设为 None 可关闭
    'trapezoid_corners': [
        (0.1, 0.2),  # 左上
        (0.68, 0.00),  # 右上
        (0.68, 1.00),  # 右下
        (0.0, 0.80),  # 左下
    ],
    # 梯形边缘柔化像素（0 表示硬边）
    'trapezoid_feather': 2,
    # 梯形外是否使用窗口透明（Windows 分层窗口 + 颜色键）来穿透显示桌面背景
    'transparent_outside': True,
    # 用作透明的颜色键（RGB），必须是画面中几乎不会出现的颜色
    'transparent_colorkey': (255, 0, 255),
}


class SensorManager:
    """传感器管理器"""
    
    def __init__(self, world, car, config):
        self.surface = None
        self.world = world
        self.car = car
        self.config = config
        
        blueprint_library = world.get_blueprint_library()
        self.camera_bp = blueprint_library.find('sensor.camera.rgb')
        sensor_w = int(config.get('sensor_width') or config['width'])
        sensor_h = int(config.get('sensor_height') or config['height'])
        # 强制宽/高为 4 的倍数，避免 CARLA 行对齐导致的斜条纹伪影
        if sensor_w % 4 != 0:
            sensor_w = sensor_w + (4 - sensor_w % 4)
        if sensor_h % 4 != 0:
            sensor_h = sensor_h + (4 - sensor_h % 4)
        self.camera_bp.set_attribute('image_size_x', str(sensor_w))
        self.camera_bp.set_attribute('image_size_y', str(sensor_h))
        self.camera_bp.set_attribute('fov', str(config['fov']))
        
        camera_transform = carla.Transform(config['location'], config['rotation'])
        self.camera = world.spawn_actor(self.camera_bp, camera_transform, attach_to=car)
        self.camera.listen(lambda image: self._parse_image(image))
        
        print(f"[{config['name']}] 相机已创建")
        
    def _parse_image(self, image):
        # 使用连续内存的 RGB 缓冲创建 surface，避免某些分辨率下出现斜条纹伪影
        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = np.reshape(array, (image.height, image.width, 4))
        rgb = array[:, :, :3][:, :, ::-1].copy(order="C")  # BGRA -> RGB，并确保连续内存
        surface = pygame.image.frombuffer(rgb.tobytes(), (image.width, image.height), "RGB")
        
        if self.config.get('flip', False):
            surface = pygame.transform.flip(surface, True, False)
            
        self.surface = surface

    def _crop_to_mirror_aspect(self, surface):
        """将原始画面居中裁剪到后视镜比例，避免“过高”的画面塞不进镜面。"""
        target_aspect = float(self.config.get('mirror_aspect', 0.0) or 0.0)
        if target_aspect <= 0.0:
            return surface

        src_w, src_h = surface.get_width(), surface.get_height()
        if src_w <= 0 or src_h <= 0:
            return surface

        src_aspect = src_w / src_h
        if abs(src_aspect - target_aspect) < 1e-3:
            return surface

        if src_aspect > target_aspect:
            # 源图太宽 -> 裁左右
            crop_w = int(src_h * target_aspect)
            crop_h = src_h
            x = max(0, (src_w - crop_w) // 2)
            y = 0
        else:
            # 源图太高 -> 裁上下
            crop_w = src_w
            crop_h = int(src_w / target_aspect)
            x = 0
            y = max(0, (src_h - crop_h) // 2)

        return surface.subsurface(pygame.Rect(x, y, crop_w, crop_h)).copy()
        
    def _get_outside_color(self):
        """梯形外填充色。启用透明时使用颜色键，否则黑色。"""
        if self.config.get('transparent_outside', False):
            ck = self.config.get('transparent_colorkey', (255, 0, 255))
            return (int(ck[0]), int(ck[1]), int(ck[2]))
        return (0, 0, 0)

    def _apply_trapezoid_mask(self, display):
        """将梯形轮廓外的区域涂成指定颜色（透明模式下为颜色键），模拟后视镜镜面形状。"""
        corners_frac = self.config.get('trapezoid_corners')
        if not corners_frac or len(corners_frac) < 3:
            return

        dw, dh = display.get_size()
        if dw <= 0 or dh <= 0:
            return

        pts = [(
            max(0, min(dw, int(round(cx * dw)))),
            max(0, min(dh, int(round(cy * dh)))),
        ) for (cx, cy) in corners_frac]

        outside = self._get_outside_color()
        inside_marker = (0, 0, 0) if outside != (0, 0, 0) else (1, 1, 1)

        mask = pygame.Surface((dw, dh))
        mask.fill(outside)
        pygame.draw.polygon(mask, inside_marker, pts)
        mask.set_colorkey(inside_marker)
        display.blit(mask, (0, 0))

        feather = int(self.config.get('trapezoid_feather', 0) or 0)
        if feather > 0:
            for i in range(len(pts)):
                p1 = pts[i]
                p2 = pts[(i + 1) % len(pts)]
                pygame.draw.line(display, outside, p1, p2, feather)

    def render(self, display):
        if self.surface is not None:
            mirror_surface = self._crop_to_mirror_aspect(self.surface)
            src_w, src_h = mirror_surface.get_size()
            dst_w, dst_h = display.get_size()
            if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
                return

            # 保持画面比例，必要时加边，避免强行拉伸引入条纹伪影
            scale = min(dst_w / src_w, dst_h / src_h)
            fit_w = max(1, int(src_w * scale))
            fit_h = max(1, int(src_h * scale))
            x = (dst_w - fit_w) // 2
            y = (dst_h - fit_h) // 2

            if (fit_w, fit_h) != (src_w, src_h):
                mirror_surface = pygame.transform.scale(mirror_surface, (fit_w, fit_h))

            display.fill(self._get_outside_color())
            display.blit(mirror_surface, (x, y))
            self._apply_trapezoid_mask(display)
            
    def destroy(self):
        if self.camera:
            self.camera.stop()
            self.camera.destroy()
            print(f"[{self.config['name']}] 相机已销毁")


def find_ego_vehicle(world, role_name='hero', timeout=30):
    """查找主车"""
    print(f"正在查找主车 (role_name={role_name})...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        actor_list = world.get_actors().filter('vehicle.*')
        for vehicle in actor_list:
            if vehicle.attributes.get('role_name') == role_name:
                print(f"找到主车: {vehicle.type_id}")
                return vehicle
        time.sleep(0.5)
        
    print(f"超时: 未找到主车 (role_name={role_name})")
    return None


def find_ego_vehicle_once(world, role_name='hero'):
    """仅做一次快速查找（不 sleep），用于 hero 重启后的自动重绑。"""
    try:
        actor_list = world.get_actors().filter('vehicle.*')
        for vehicle in actor_list:
            try:
                if vehicle.attributes.get('role_name') == role_name:
                    return vehicle
            except Exception:
                continue
    except Exception:
        return None
    return None


def set_window_position(x, y):
    """设置窗口位置 (跨平台)"""
    os.environ['SDL_VIDEO_WINDOW_POS'] = f'{x},{y}'


def _get_windows_monitor_bounds_sorted():
    """
    获取Windows所有显示器的虚拟桌面坐标（按 X,Y 排序）。
    返回: [(left, top, width, height), ...]
    """
    if os.name != 'nt':
        return []

    user32 = ctypes.windll.user32
    monitors = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _callback(hmonitor, hdc, lprect, lparam):
        r = lprect.contents
        monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_callback), 0)
    monitors.sort(key=lambda t: (t[0], t[1]))
    return monitors


def _enable_window_transparency(colorkey_rgb):
    """Windows: 将当前 pygame 窗口设置为分层窗口，并使指定 RGB 颜色完全透明。"""
    if os.name != 'nt':
        return False
    try:
        hwnd = pygame.display.get_wm_info().get("window")
        if not hwnd:
            return False

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        LWA_COLORKEY = 0x00000001

        user32 = ctypes.windll.user32
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
        user32.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, wintypes.COLORREF, ctypes.c_byte, wintypes.DWORD
        ]

        styles = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, styles | WS_EX_LAYERED)

        r, g, b = colorkey_rgb
        colorref = (int(b) << 16) | (int(g) << 8) | int(r)
        user32.SetLayeredWindowAttributes(hwnd, colorref, 255, LWA_COLORKEY)
        return True
    except Exception as e:
        print(f"[警告] 设置窗口透明失败: {e}")
        return False


def _get_monitor_origin(display_index: int):
    monitors = _get_windows_monitor_bounds_sorted()
    if not monitors:
        return 0, 0
    if 0 <= display_index < len(monitors):
        left, top, _, _ = monitors[display_index]
        return left, top
    left, top, _, _ = monitors[0]
    return left, top


def main():
    argparser = argparse.ArgumentParser(description='左后视镜相机')
    argparser.add_argument('--host', default='127.0.0.1', help='CARLA服务器IP')
    argparser.add_argument('-p', '--port', default=2000, type=int, help='CARLA服务器端口')
    argparser.add_argument('--display', default=0, type=int, help='显示器编号')
    argparser.add_argument('--width', default=CAMERA_CONFIG['width'], type=int, help='窗口宽度')
    argparser.add_argument('--height', default=CAMERA_CONFIG['height'], type=int, help='窗口高度')
    argparser.add_argument('--mirror-aspect', default=CAMERA_CONFIG['mirror_aspect'], type=float,
                          help='后视镜画幅宽高比（默认 8/3）')
    argparser.add_argument('--trapezoid', default=None, type=str,
                          help='梯形遮罩 4 个角点，按 [左上, 右上, 右下, 左下] 顺序的 x,y 比例，共 8 个 0~1 数字，逗号分隔。例: 0.08,0.06,0.94,0,1,1,0,0.94')
    argparser.add_argument('--no-trapezoid', action='store_true', help='关闭梯形遮罩')
    argparser.add_argument('--trapezoid-feather', default=CAMERA_CONFIG.get('trapezoid_feather', 0), type=int,
                          help='梯形边缘柔化像素，0 为硬边')
    argparser.add_argument('--no-transparent', action='store_true',
                          help='关闭窗口透明（梯形外会显示为黑色）')
    argparser.add_argument('--colorkey', default=None, type=str,
                          help='透明颜色键（RGB），格式 R,G,B，默认 255,0,255')
    argparser.add_argument('--pos-x', default=0, type=int, help='窗口X位置（相对该显示器左上角）')
    argparser.add_argument('--pos-y', default=700, type=int, help='窗口Y位置（相对该显示器左上角）')
    argparser.add_argument('--rolename', default='hero', help='主车角色名')
    argparser.add_argument('--rebind-interval', default=1.0, type=float,
                          help='当 hero 重启/切换实验后自动重绑相机的检测间隔(秒)')
    args = argparser.parse_args()
    
    CAMERA_CONFIG['width'] = args.width
    CAMERA_CONFIG['height'] = args.height
    CAMERA_CONFIG['mirror_aspect'] = max(0.1, float(args.mirror_aspect))
    CAMERA_CONFIG['trapezoid_feather'] = max(0, int(args.trapezoid_feather))

    if args.colorkey:
        try:
            parts = [int(v) for v in args.colorkey.split(',')]
            if len(parts) != 3:
                raise ValueError('需要 3 个数字')
            CAMERA_CONFIG['transparent_colorkey'] = tuple(max(0, min(255, v)) for v in parts)
        except Exception as e:
            print(f"[警告] --colorkey 参数无效 ({e})，将使用默认颜色键")

    CAMERA_CONFIG['transparent_outside'] = (not args.no_transparent) and (os.name == 'nt')

    if args.no_trapezoid:
        CAMERA_CONFIG['trapezoid_corners'] = None
    elif args.trapezoid:
        try:
            nums = [float(v) for v in args.trapezoid.split(',') if v.strip() != '']
            if len(nums) != 8:
                raise ValueError('需要 8 个数字')
            corners = [
                (nums[0], nums[1]),
                (nums[2], nums[3]),
                (nums[4], nums[5]),
                (nums[6], nums[7]),
            ]
            corners = [(max(0.0, min(1.0, x)), max(0.0, min(1.0, y))) for (x, y) in corners]
            CAMERA_CONFIG['trapezoid_corners'] = corners
        except Exception as e:
            print(f"[警告] --trapezoid 参数无效 ({e})，将使用默认梯形")
    
    # 设置窗口位置（在Windows上通过虚拟桌面坐标强制落在指定屏幕）
    base_x, base_y = _get_monitor_origin(args.display)
    set_window_position(base_x + args.pos_x, base_y + args.pos_y)
    
    pygame.init()
    pygame.font.init()
    sensor = None
    
    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(20.0)
        world = client.get_world()
        
        display_flags = pygame.NOFRAME | pygame.DOUBLEBUF
            
        display = pygame.display.set_mode(
            (args.width, args.height), 
            display_flags, 
            display=args.display
        )
        pygame.display.set_caption(CAMERA_CONFIG['name'])

        if CAMERA_CONFIG.get('transparent_outside', False):
            ok = _enable_window_transparency(CAMERA_CONFIG['transparent_colorkey'])
            if not ok:
                CAMERA_CONFIG['transparent_outside'] = False

        car = find_ego_vehicle(world, args.rolename)
        if car is None:
            print("错误: 找不到主车，请先运行主脚本")
            return
            
        sensor = SensorManager(world, car, CAMERA_CONFIG)
        
        clock = pygame.time.Clock()
        
        print(f"\n[{CAMERA_CONFIG['name']}] 运行中...")
        print("按 ESC 或关闭窗口退出")

        last_rebind_check = 0.0
        
        while True:
            clock.tick_busy_loop(30)
            
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return

            now = time.time()
            if now - last_rebind_check >= args.rebind_interval:
                last_rebind_check = now
                new_car = find_ego_vehicle_once(world, args.rolename)
                new_id = getattr(new_car, "id", None) if new_car is not None else None
                cur_id = getattr(car, "id", None) if car is not None else None
                if new_car is not None and (car is None or new_id != cur_id):
                    car = new_car
                    if sensor:
                        sensor.destroy()
                    sensor = SensorManager(world, car, CAMERA_CONFIG)
                    print(f"[{CAMERA_CONFIG['name']}] hero 已重绑 (id {cur_id} -> {new_id})")
                        
            world.wait_for_tick()
            sensor.render(display)
            pygame.display.flip()
            
    except Exception as e:
        print(f"错误: {e}")
        
    finally:
        if sensor:
            sensor.destroy()
        pygame.quit()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n用户中断')
