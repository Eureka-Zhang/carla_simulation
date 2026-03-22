# 跟驰实验 CARLA 仿真系统

## 概述

本系统用于驾驶模拟器上的跟驰实验，支持：
- 驾驶舱硬件接入（完整UDP通信协议）
- 键盘控制（PC测试模式）
- 多视角相机（独立脚本，支持多显示器）
- 跟驰场景数据采集
- 仿真录制回放

## 文件结构

```
car_following_experiment/
├── car_following_experiment.py    # 主脚本
├── cameras/                       # 独立相机脚本
│   ├── Left.py                    # 左侧视角 (1920x1080)
│   ├── Right.py                   # 右侧视角 (1920x1080)
│   ├── Back.py                    # 后视相机 (256x144)
│   ├── LeftBack.py                # 左后视镜 (384x216)
│   ├── RightBack.py               # 右后视镜 (320x180)
│   └── launch_all.sh              # 批量启动脚本
├── requirements.txt               # 依赖包
└── README_CarFollowingExperiment.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动CARLA服务器

```bash
# Linux
./CarlaUE4.sh

# Windows
CarlaUE4.exe
```

### 3. 运行主脚本

```bash
# 键盘控制模式
python car_following_experiment.py --keyboard

# 驾驶舱控制模式
python car_following_experiment.py --cabin

# 指定显示器和分辨率
python car_following_experiment.py --keyboard --display 0 --res 1920x1080

# 全屏模式
python car_following_experiment.py --keyboard --fullscreen
```

### 4. 启动多视角相机（可选）

在主脚本运行后，启动额外的相机视角：

```bash
# 单独启动某个相机
cd cameras
python Left.py --display 1 --fullscreen
python Right.py --display 2 --fullscreen

# 批量启动所有相机
chmod +x launch_all.sh
./launch_all.sh
```

## 命令行参数

### 主脚本参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | 127.0.0.1 | CARLA服务器IP |
| `--port` | 2000 | CARLA服务器端口 |
| `--res` | 1280x720 | 窗口分辨率 |
| `--display` | 0 | 显示器编号 |
| `--fullscreen` | - | 全屏模式 |
| `--keyboard` | - | 键盘控制模式 |
| `--cabin` | - | 驾驶舱控制模式 |
| `--cabin-ip` | 192.168.0.20 | 驾驶舱IP地址 |
| `--cabin-port` | 3232 | 驾驶舱端口 |
| `--lead-speed` | 20.0 | 前车基准速度(m/s) |
| `--lead-random` | - | 前车使用随机速度曲线 |
| `--lead-seed` | 自动 | 随机种子（用于复现实验） |
| `--map` | Town04 | 地图名称 |
| `--filter` | vehicle.audi.tt | 自车蓝图 |
| `--sync` / `--no-sync` | 启用 | 同步模式 |

### 相机脚本参数

| 参数 | 说明 |
|------|------|
| `--display` | 显示器编号 |
| `--width` / `--height` | 窗口尺寸 |
| `--fullscreen` | 全屏模式 |
| `--pos-x` / `--pos-y` | 窗口位置（小窗口） |
| `--rolename` | 主车角色名（默认hero） |

## 按键说明

### 驾驶控制
| 按键 | 功能 |
|------|------|
| W / ↑ | 油门 |
| S / ↓ | 制动 |
| A / D | 转向 |
| Q | 切换倒档 |
| Space | 手刹 |
| M | 手动/自动变速 |
| , / . | 降档/升档 |

### 功能控制
| 按键 | 功能 |
|------|------|
| F1 | 开始/停止数据采集 |
| F2 | 切换手动/自动驾驶（跟驰模型） |
| F3 | 切换前车行为（恒速→固定曲线→随机） |
| P | 切换CARLA自动驾驶 |
| F | 切换Ackermann控制 |

### 车灯控制
| 按键 | 功能 |
|------|------|
| L | 切换车灯（位置灯→近光灯→雾灯→关闭） |
| Shift+L | 远光灯 |
| Z | 左转向灯 |
| X | 右转向灯 |
| I | 内饰灯 |

### 视图控制
| 按键 | 功能 |
|------|------|
| TAB | 切换相机视角 |
| N / ` | 下一个传感器 |
| 1-9 | 选择传感器 |
| G | 雷达可视化 |
| C | 切换天气 |
| V | 切换地图层 |
| B | 加载/卸载地图层 |

### 录制控制
| 按键 | 功能 |
|------|------|
| R | 录制图像 |
| Ctrl+R | 开始/停止录制仿真 |
| Ctrl+P | 回放录制 |
| Ctrl+- / Ctrl+= | 调整回放起始时间 |

### 其他
| 按键 | 功能 |
|------|------|
| H | 显示帮助 |
| O | 开/关车门 |
| T | 显示遥测信息 |
| Backspace | 重启场景 |
| ESC | 退出 |

## 数据采集

按 F1 开始数据采集，数据保存在 `./experiment_data/` 目录下。

### 采集的数据字段

| 字段 | 说明 |
|------|------|
| timestamp | 时间戳(秒) |
| frame | 帧序号 |
| ego_speed | 自车速度(m/s) |
| ego_acceleration | 自车加速度(m/s²) |
| ego_jerk | 自车加加速度(m/s³) |
| ego_pos_x, ego_pos_y | 自车位置 |
| lead_speed | 前车速度(m/s) |
| lead_acceleration | 前车加速度(m/s²) |
| distance_headway | 车头间距(m) |
| time_headway | 时距(s) |
| relative_speed | 相对速度(m/s) |
| ttc | 碰撞时间(s) |
| throttle | 油门(0-1) |
| brake | 制动(0-1) |
| steer | 转向(-1~1) |
| longitudinal_control | 纵向控制信号 |
| control_mode | 控制模式 |
| gear | 挡位 |
| lead_target_speed | 前车目标速度(m/s) |
| lead_behavior_mode | 前车行为模式 |

## 前车行为模式

按 **F3** 在三种模式间切换：

| 模式 | 说明 |
|------|------|
| `constant` | 恒定速度（默认 72 km/h） |
| `fixed` | 预定义速度曲线，所有被试相同 |
| `random` | 随机生成速度曲线 |

### 随机模式特点

- **速度范围**: 12-28 m/s (43-100 km/h)
- **最大加速度**: 2 m/s²
- **最大减速度**: 3 m/s²
- **变化间隔**: 15-45 秒
- **随机种子**: 自动保存在 `_metadata.json` 中，可用于复现

### 启动时指定随机模式

```bash
# 使用随机速度曲线
python car_following_experiment.py --keyboard --lead-random

# 指定随机种子（复现实验）
python car_following_experiment.py --keyboard --lead-random --lead-seed 12345
```

## 驾驶舱通信协议

### 发送到驾驶舱 (68字节)

```
struct SendData {
    uint32_t field_count;      // 固定值15
    float engine_rpm;          // 发动机转速
    float speed;               // 车速 km/h
    float force_feedback;      // 方向盘力反馈
    float reserved[13];        // 保留字段
};
```

### 从驾驶舱接收 (164字节)

```
struct RecvData {
    uint32_t analog_count;     // 模拟量个数
    float throttle;            // 油门 (0-1)
    float brake;               // 制动 (0-1)
    float clutch;              // 离合
    float steer;               // 方向盘角度
    float handbrake;           // 手刹
    float reserved[4];         // 保留
    
    uint32_t digital_count;    // 开关量个数
    uint32_t ignition_on;      // 点火开
    uint32_t ignition_off;     // 点火关
    uint32_t left_blinker;     // 左转向灯
    uint32_t right_blinker;    // 右转向灯
    uint32_t hazard;           // 警告灯
    uint32_t reserved2[2];
    uint32_t low_beam;         // 近光灯
    uint32_t high_beam;        // 远光灯
    // ... 更多开关量
    uint32_t gear_d;           // D档 [33]
    uint32_t gear_p;           // P档 [34]
    uint32_t gear_n;           // N档 [35]
    uint32_t gear_r;           // R档 [36]
};
```

## 多显示器配置

典型的三显示器配置：

```
显示器0 (主): 主驾驶视角 + 后视镜小窗口
显示器1 (左): 左侧窗户视角 (全屏)
显示器2 (右): 右侧窗户视角 (全屏)
```

启动命令示例：

```bash
# 终端1: 主脚本
python car_following_experiment.py --display 0 --res 1920x1080

# 终端2: 左侧视角
python cameras/Left.py --display 1 --fullscreen

# 终端3: 右侧视角
python cameras/Right.py --display 2 --fullscreen
```

## 故障排除

### 找不到主车
确保主脚本已运行且车辆已生成，相机脚本会等待30秒查找主车。

### 显示器编号
使用 `xrandr` (Linux) 或显示设置 (Windows) 查看显示器编号。

### UDP通信问题
检查驾驶舱IP地址和端口配置，确保网络连接正常。

## 实验流程

1. **Phase 1**: 被试手动驾驶，采集纵向控制数据
2. **Phase 2**: (离线) 使用采集数据训练个性化跟驰模型
3. **Phase 3**: 被试作为乘客体验自动驾驶

## License

MIT License
