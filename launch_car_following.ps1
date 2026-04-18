$ErrorActionPreference = "Stop"

# 一键启动「跟驰实验」主视角 + 多相机视角（每个进程一个独立终端窗口）
# 仅运行 following 实验组（180s 的 following_irregular）
# 用法：
#   1) 在项目根目录执行：powershell -ExecutionPolicy Bypass -File .\launch_car_following.ps1
#   2) 或直接双击 launch_car_following.bat

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$condaEnvName = "carla39"

# 优先使用常见 Anaconda 安装路径的 activate.bat，找不到时回退到 conda 命令
$condaActivateCandidates = @(
    "D:\anaconda\Scripts\activate.bat",
    "C:\ProgramData\anaconda3\Scripts\activate.bat",
    "$env:USERPROFILE\anaconda3\Scripts\activate.bat",
    "$env:USERPROFILE\miniconda3\Scripts\activate.bat"
)
$condaActivateBat = $condaActivateCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

function Start-ViewTerminal($title, $command) {
    if ($condaActivateBat) {
        $cmdLine = "title $title && cd /d `"$projectRoot`" && call `"$condaActivateBat`" $condaEnvName && $command"
    } else {
        $cmdLine = "title $title && cd /d `"$projectRoot`" && conda activate $condaEnvName && $command"
    }
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", $cmdLine) | Out-Null
}

Start-ViewTerminal "CARLA Following Main View" "python .\car_following_experiment.py --host 127.0.0.1 --port 2000 --cabin --display 2 --res 1920x1080 --cabin-echo-interval 0.25 --four-experiments --experiment-scope following"
Start-ViewTerminal "CARLA Left Camera"         "python .\cameras\Left.py --host 127.0.0.1 --port 2000 --display 1"
Start-ViewTerminal "CARLA Right Camera"        "python .\cameras\Right.py --host 127.0.0.1 --port 2000 --display 3"
Start-ViewTerminal "CARLA Back Camera"         "python .\cameras\Back.py --host 127.0.0.1 --port 2000 --display 1 --pos-x 832 --pos-y 20"
Start-ViewTerminal "CARLA LeftBack Camera"     "python .\cameras\LeftBack.py --host 127.0.0.1 --port 2000 --display 0 --pos-x 975 --pos-y 700"
Start-ViewTerminal "CARLA RightBack Camera"    "python .\cameras\RightBack.py --host 127.0.0.1 --port 2000 --display 2 --pos-x 975 --pos-y 760"

exit 0
