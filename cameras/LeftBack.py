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
    'width': 384,
    'height': 216,
    'fov': 100,
    # 相机位置：左后视镜视角
    'location': carla.Location(x=0.4, y=-1, z=1.1),
    'rotation': carla.Rotation(pitch=-3, yaw=160),
    'flip': True,  # 后视镜需要翻转
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
        self.camera_bp.set_attribute('image_size_x', str(config['width']))
        self.camera_bp.set_attribute('image_size_y', str(config['height']))
        self.camera_bp.set_attribute('fov', str(config['fov']))
        
        camera_transform = carla.Transform(config['location'], config['rotation'])
        self.camera = world.spawn_actor(self.camera_bp, camera_transform, attach_to=car)
        self.camera.listen(lambda image: self._parse_image(image))
        
        print(f"[{config['name']}] 相机已创建")
        
    def _parse_image(self, image):
        array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
        array = np.reshape(array, (image.height, image.width, 4))
        array = array[:, :, :3]
        array = array[:, :, ::-1]
        surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
        
        if self.config.get('flip', False):
            surface = pygame.transform.flip(surface, True, False)
            
        self.surface = surface
        
    def render(self, display):
        if self.surface is not None:
            display.blit(self.surface, (0, 0))
            
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
    argparser.add_argument('--pos-x', default=0, type=int, help='窗口X位置（相对该显示器左上角）')
    argparser.add_argument('--pos-y', default=700, type=int, help='窗口Y位置（相对该显示器左上角）')
    argparser.add_argument('--rolename', default='hero', help='主车角色名')
    argparser.add_argument('--rebind-interval', default=1.0, type=float,
                          help='当 hero 重启/切换实验后自动重绑相机的检测间隔(秒)')
    args = argparser.parse_args()
    
    CAMERA_CONFIG['width'] = args.width
    CAMERA_CONFIG['height'] = args.height
    
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
