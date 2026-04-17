$ErrorActionPreference = "Stop"

# 一键启动主视角 + 多相机视角（每个进程一个独立终端窗口）
# 用法：
#   1) 在项目根目录执行：powershell -ExecutionPolicy Bypass -File .\launch_all_views.ps1
#   2) 或直接右键“使用 PowerShell 运行”

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

$jobs = @(
    @{
        Title   = "CARLA Main View"
        Command = "python .\car_following_experiment.py --host 127.0.0.1 --port 2000 --cabin --display 2 --res 1920x1080 --cabin-echo-interval 0.25 --six-experiments"
    },
    @{
        Title   = "CARLA Left Camera"
        Command = "python .\cameras\Left.py --host 127.0.0.1 --port 2000 --display 1"
    },
    @{
        Title   = "CARLA Right Camera"
        Command = "python .\cameras\Right.py --host 127.0.0.1 --port 2000 --display 3"
    },
    @{
        Title   = "CARLA Back Camera"
        Command = "python .\cameras\Back.py --host 127.0.0.1 --port 2000 --display 1 --pos-x 832 --pos-y 20"
    },
    @{
        Title   = "CARLA LeftBack Camera"
        Command = "python .\cameras\LeftBack.py --host 127.0.0.1 --port 2000 --display 0 --pos-x 900 --pos-y 700"
    },
    @{
        Title   = "CARLA RightBack Camera"
        Command = "python .\cameras\RightBack.py --host 127.0.0.1 --port 2000 --display 2 --pos-x 1050 --pos-y 760"
    }
)

foreach ($job in $jobs) {
    if ($condaActivateBat) {
        $cmdLine = "title $($job.Title) && cd /d `"$projectRoot`" && call `"$condaActivateBat`" $condaEnvName && $($job.Command)"
    } else {
        $cmdLine = "title $($job.Title) && cd /d `"$projectRoot`" && conda activate $condaEnvName && $($job.Command)"
    }

    Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", $cmdLine) | Out-Null
    Start-Sleep -Milliseconds 300
}

if ($condaActivateBat) {
    Write-Host "已启动全部视角终端窗口（已配置 conda activate $condaEnvName）。" -ForegroundColor Green
} else {
    Write-Host "已启动全部视角终端窗口。未找到 activate.bat，将依赖 conda 命令可用性。" -ForegroundColor Yellow
}
