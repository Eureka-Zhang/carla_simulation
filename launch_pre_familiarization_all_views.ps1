param(
    [switch]$ForceMultiDisplay
)

$ErrorActionPreference = "Stop"

# 一键启动前置熟悉实验主视角 + 多相机视角（每个进程一个独立终端窗口）
# 用法：
#   1) 在项目根目录执行：powershell -ExecutionPolicy Bypass -File .\launch_pre_familiarization_all_views.ps1
#   2) 或直接右键“使用 PowerShell 运行”
# 多屏布局需要至少 4 台显示器（脚本使用 display 0–3）。不足时自动改为全部 --display 0，避免 Pygame 无法建窗。
# 若确有多屏但检测异常，可加：-ForceMultiDisplay

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

# 本启动器使用的最大显示器编号为 3，需至少 4 块屏才能安全使用原布局；否则 Pygame set_mode(display=N) 会失败（表现为“没有窗口”）。
$minimumScreensForLayout = 4
try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    $screenCount = [System.Windows.Forms.Screen]::AllScreens.Count
}
catch {
    $screenCount = 1
}
$useMultiDisplayLayout = $ForceMultiDisplay -or ($screenCount -ge $minimumScreensForLayout)

$jobs = @(
    @{
        Title   = "CARLA Pre Familiarization Main View"
        Command = "python .\pre_familiarization_experiment.py --host 127.0.0.1 --port 2000 --cabin --display 2 --res 1920x1080"
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
        Command = "python .\cameras\LeftBack.py --host 127.0.0.1 --port 2000 --display 0 --pos-x 975 --pos-y 700"
    },
    @{
        Title   = "CARLA RightBack Camera"
        Command = "python .\cameras\RightBack.py --host 127.0.0.1 --port 2000 --display 2 --pos-x 975 --pos-y 760"
    }
)

if (-not $useMultiDisplayLayout) {
    Write-Host "检测到显示器数量: $screenCount （多屏布局至少需要 $minimumScreensForLayout 台）。已将各窗口改为 --display 0（主显示器）。" -ForegroundColor Yellow
    $jobs = foreach ($j in $jobs) {
        @{ Title = $j.Title; Command = ($j.Command -replace '--display\s+\d+', '--display 0') }
    }
}

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
    Write-Host "已启动前置熟悉实验全部视角终端窗口（已配置 conda activate $condaEnvName）。" -ForegroundColor Green
} else {
    Write-Host "已启动前置熟悉实验全部视角终端窗口。未找到 activate.bat，将依赖 conda 命令可用性。" -ForegroundColor Yellow
}
