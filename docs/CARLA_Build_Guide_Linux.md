# CARLA 源码编译与地图导入指南 (Ubuntu 20.04)

## 前置条件检查

### 已安装
- Ubuntu 20.04 LTS
- Python 3.7+
- CMake 3.28
- Make 4.2
- GCC 9.4
- Clang 8.0

### 需要安装
1. Unreal Engine 4.26 (CARLA 0.9.12 对应版本)
2. 额外依赖包

---

## 第一步：安装系统依赖

```bash
# 更新系统
sudo apt-get update

# 安装编译依赖
sudo apt-get install -y \
    build-essential \
    clang-10 \
    lld-10 \
    g++-7 \
    cmake \
    ninja-build \
    libvulkan1 \
    python3 \
    python3-dev \
    python3-pip \
    libpng-dev \
    libtiff5-dev \
    libjpeg-dev \
    tzdata \
    sed \
    curl \
    unzip \
    autoconf \
    libtool \
    rsync \
    libxml2-dev \
    git

# 安装 pip 依赖
pip3 install --upgrade pip
pip3 install --user setuptools
pip3 install --user distro
```

---

## 第二步：安装 Unreal Engine 4.26

### 2.1 注册 Epic Games 账号
1. 访问 https://www.unrealengine.com/
2. 注册账号并登录
3. 关联 GitHub 账号：https://www.unrealengine.com/account/connections

### 2.2 加入 Epic Games GitHub 组织
1. 接受 GitHub 邮件邀请
2. 确认可以访问：https://github.com/EpicGames

### 2.3 下载 CARLA 定制版 Unreal Engine

```bash
# 创建目录
mkdir -p ~/UnrealEngine_4.26
cd ~/UnrealEngine_4.26

# 克隆 CARLA 定制的 UE4 分支
git clone --depth 1 -b carla https://github.com/CarlaUnreal/UnrealEngine.git .

# 注意：需要 GitHub 账号已关联 Epic Games
# 如果克隆失败，检查是否已接受 Epic Games 邀请
```

### 2.4 编译 Unreal Engine

```bash
cd ~/UnrealEngine_4.26

# 运行设置脚本
./Setup.sh

# 生成项目文件
./GenerateProjectFiles.sh

# 编译 (需要 4-8 小时，取决于 CPU)
make -j$(nproc)

# 验证安装
ls Engine/Binaries/Linux/UE4Editor
```

### 2.5 设置环境变量

```bash
# 添加到 ~/.bashrc
echo 'export UE4_ROOT=~/UnrealEngine_4.26' >> ~/.bashrc
source ~/.bashrc

# 验证
echo $UE4_ROOT
```

---

## 第三步：从源码构建 CARLA

### 3.1 克隆 CARLA 源码

```bash
cd ~
git clone https://github.com/carla-simulator/carla.git
cd carla

# 切换到 0.9.12 版本
git checkout 0.9.12
```

### 3.2 获取 CARLA 资源

```bash
# 下载资源文件 (约 3GB)
./Update.sh
```

### 3.3 编译 CARLA

```bash
# 设置 Unreal Engine 路径
export UE4_ROOT=~/UnrealEngine_4.26

# 编译 CARLA 客户端
make PythonAPI

# 编译 CARLA 服务端
make launch

# 打包发布版
make package
```

---

## 第四步：导入自定义地图

### 4.1 准备地图文件

确保你有以下文件：
- `YourMap.fbx` - 3D 模型
- `YourMap.xodr` - OpenDRIVE 道路定义

### 4.2 创建地图目录

```bash
cd ~/carla/Import

# 创建地图文件夹
mkdir -p YourMap

# 复制文件
cp /path/to/YourMap.fbx YourMap/
cp /path/to/YourMap.xodr YourMap/
```

### 4.3 创建 JSON 配置文件

```bash
cat > YourMap/YourMap.json << 'EOF'
{
    "maps": [
        {
            "name": "YourMap",
            "source": "./YourMap.fbx",
            "xodr": "./YourMap.xodr",
            "use_carla_materials": true
        }
    ]
}
EOF
```

### 4.4 运行导入脚本

```bash
cd ~/carla

# 导入地图
make import ARGS="--package=YourMap"
```

### 4.5 编译并打包

```bash
# 重新打包包含新地图
make package ARGS="--packages=YourMap"
```

---

## 第五步：使用自定义地图

### 5.1 启动 CARLA

```bash
cd ~/carla/Dist/CARLA_Shipping_0.9.12-*/LinuxNoEditor
./CarlaUE4.sh
```

### 5.2 加载地图

```python
import carla

client = carla.Client('localhost', 2000)
client.set_timeout(10.0)

# 列出可用地图
print(client.get_available_maps())

# 加载自定义地图
client.load_world('YourMap')
```

---

## 常见问题

### Q1: git clone Unreal Engine 失败
- 确保已注册 Epic Games 账号
- 确保已关联 GitHub 账号
- 确保已接受组织邀请

### Q2: 编译时间太长
- Unreal Engine 编译需要 4-8 小时
- 建议使用 8 核以上 CPU
- 确保有 100GB+ 磁盘空间

### Q3: 内存不足
- UE4 编译需要 16GB+ RAM
- 可以添加 swap 空间

```bash
sudo fallocate -l 16G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## 参考链接

- CARLA Linux 构建指南: https://carla.readthedocs.io/en/0.9.12/build_linux/
- CARLA 地图导入: https://carla.readthedocs.io/en/0.9.12/tuto_M_add_map_package/
- Unreal Engine 文档: https://docs.unrealengine.com/
