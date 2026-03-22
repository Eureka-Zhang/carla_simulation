#!/usr/bin/env python3
"""
扫描 CARLA 地图，找到最长的直道段
"""

import carla
import math
import sys

def measure_straight_length(world, waypoint, max_distance=5000):
    """从给定 waypoint 开始测量直道长度"""
    if waypoint is None:
        return 0, 0
    
    initial_yaw = waypoint.transform.rotation.yaw
    total_distance = 0
    current_wp = waypoint
    max_yaw_diff = 0
    
    while total_distance < max_distance:
        next_wps = current_wp.next(5.0)  # 每 5 米检查一次
        if not next_wps:
            break
        
        next_wp = next_wps[0]
        current_yaw = next_wp.transform.rotation.yaw
        
        # 计算与初始方向的偏差
        yaw_diff = abs(current_yaw - initial_yaw)
        if yaw_diff > 180:
            yaw_diff = 360 - yaw_diff
        
        max_yaw_diff = max(max_yaw_diff, yaw_diff)
        
        # 如果偏差超过 10 度，认为直道结束
        if yaw_diff > 10:
            break
        
        total_distance += 5.0
        current_wp = next_wp
    
    return total_distance, max_yaw_diff


def find_straight_roads(host='127.0.0.1', port=2000, map_name='Town04'):
    """扫描地图找到所有直道"""
    client = carla.Client(host, port)
    client.set_timeout(10.0)
    
    # 加载地图
    world = client.load_world(map_name)
    carla_map = world.get_map()
    
    print(f"\n扫描地图: {map_name}")
    print("=" * 60)
    
    spawn_points = carla_map.get_spawn_points()
    print(f"总生成点数: {len(spawn_points)}")
    print("\n分析各生成点前方直道长度...\n")
    
    results = []
    
    for i, sp in enumerate(spawn_points):
        waypoint = carla_map.get_waypoint(sp.location)
        straight_length, max_yaw = measure_straight_length(world, waypoint)
        
        results.append({
            'index': i,
            'x': sp.location.x,
            'y': sp.location.y,
            'yaw': sp.rotation.yaw,
            'straight_length': straight_length,
            'max_yaw_diff': max_yaw,
            'road_id': waypoint.road_id if waypoint else -1,
            'lane_id': waypoint.lane_id if waypoint else 0
        })
        
        if straight_length >= 500:  # 只显示 500m 以上的
            print(f"  [生成点 {i:3d}] 直道长度: {straight_length:6.0f}m | "
                  f"位置: ({sp.location.x:7.1f}, {sp.location.y:7.1f}) | "
                  f"道路ID: {waypoint.road_id if waypoint else -1}")
    
    # 排序找出最长的
    results.sort(key=lambda x: x['straight_length'], reverse=True)
    
    print("\n" + "=" * 60)
    print("最长直道 TOP 10:")
    print("=" * 60)
    
    for i, r in enumerate(results[:10]):
        print(f"  {i+1}. 生成点 [{r['index']:3d}]: {r['straight_length']:6.0f}m 直道")
        print(f"     位置: ({r['x']:7.1f}, {r['y']:7.1f})")
        print(f"     道路ID: {r['road_id']}, 车道: {r['lane_id']}")
        print()
    
    if results:
        best = results[0]
        print("=" * 60)
        print(f"推荐使用: --spawn-point {best['index']}")
        print(f"直道长度: {best['straight_length']:.0f} 米")
        print("=" * 60)
    
    return results


if __name__ == '__main__':
    map_name = sys.argv[1] if len(sys.argv) > 1 else 'Town04'
    find_straight_roads(map_name=map_name)
