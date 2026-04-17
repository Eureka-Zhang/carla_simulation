@echo off
REM 低画质启动 CARLA 服务端（大幅提升服务端 FPS）
REM 参数说明：
REM   -quality-level=Low   画质档位（Low/Epic），Low 能让服务端渲染快 2~3 倍
REM   -windowed            窗口模式，避免占满主屏
REM   -ResX -ResY          服务端预览窗口分辨率（不影响客户端相机）
REM   -benchmark -fps=30   锁定内部时间步 30Hz，防止空转

cd /d "E:\0.9.14-dirty\WindowsNoEditor"
start "" "CarlaUE4.exe" -quality-level=Epic -windowed -ResX=1280 -ResY=720 -benchmark -fps=30
