#!/bin/bash
# 启动所有相机视图
# Launch all camera views
#
# 用法: ./launch_all.sh
# 
# 注意: 请先运行主脚本 car_following_experiment.py

echo "启动多视角相机..."
echo "确保主脚本已经运行并生成了车辆"
echo ""

# 等待用户确认
read -p "按 Enter 继续启动相机..." 

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 启动各相机 (在后台运行)
echo "启动左侧相机 (display=1)..."
python3 "$SCRIPT_DIR/Left.py" --display 1 --fullscreen &
sleep 1

echo "启动右侧相机 (display=2)..."
python3 "$SCRIPT_DIR/Right.py" --display 2 --fullscreen &
sleep 1

echo "启动后视相机 (display=0)..."
python3 "$SCRIPT_DIR/Back.py" --display 0 --pos-x 512 --pos-y 0 &
sleep 0.5

echo "启动左后视镜 (display=1)..."
python3 "$SCRIPT_DIR/LeftBack.py" --display 1 --pos-x 0 --pos-y 700 &
sleep 0.5

echo "启动右后视镜 (display=2)..."
python3 "$SCRIPT_DIR/RightBack.py" --display 2 --pos-x 0 --pos-y 650 &

echo ""
echo "所有相机已启动!"
echo "按 Ctrl+C 停止所有相机"

# 等待所有后台进程
wait
