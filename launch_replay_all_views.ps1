# 轨迹回放 + 多相机视角（与 launch_all_views.ps1 布局一致）
# 自车 role_name=hero，侧视/后视脚本会附着回放中的自车；同步模式下由 replay 的 world.tick() 驱动各相机。
#
# 用法（在项目根目录）:
#   powershell -ExecutionPolicy Bypass -File .\launch_replay_all_views.ps1 -CsvPath ".\experiment_data\xxx\driving_data.csv"
#   L3（空格心理接管提示）: 加 -ReplayMode L3；默认 L4 使用 tools\replay_trajectory.py
# 未传 -CsvPath 时（例如双击本脚本）会弹出文件框选择 driving_data.csv；或双击 launch_replay_all_views_gui.bat / launch_replay_all_views_l3.bat
#
# 可选: -CarlaHost / -CarlaPort / -CameraStartupDelaySec（秒，回放窗口先启动，再开相机，避免找不到 hero）
# 多屏布局需至少 4 台显示器（使用 display 0–3）；不足时自动改为全部 --display 0。-ForceMultiDisplay 可跳过回退。

param(
    [Parameter(Mandatory = $false, Position = 0)]
    [string]$CsvPath = '',
    [string]$CarlaHost = "127.0.0.1",
    [int]$CarlaPort = 2000,
    [double]$CameraStartupDelaySec = 1.5,
    [ValidateSet('L4', 'L3')]
    [string]$ReplayMode = 'L4',
    [switch]$ForceMultiDisplay
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$condaEnvName = "carla39"

function Get-CsvPathViaOpenFileDialogSta {
    param([string]$Root)
    # WinForms OpenFileDialog requires STA; pwsh / MTA thread throws — run picker on STA runspace
    $picker = {
        param($R)
        Add-Type -AssemblyName System.Windows.Forms
        $exp = Join-Path $R 'experiment_data'
        $dlg = New-Object System.Windows.Forms.OpenFileDialog
        $dlg.Filter = 'CSV (*.csv)|*.csv|All files (*.*)|*.*'
        $dlg.Title = 'Select driving_data.csv for replay'
        if (Test-Path -LiteralPath $exp) { $dlg.InitialDirectory = $exp } else { $dlg.InitialDirectory = $R }
        $dlg.FileName = 'driving_data.csv'
        if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            return $dlg.FileName
        }
        return [string]::Empty
    }
    $rs = [runspacefactory]::CreateRunspace()
    $rs.ApartmentState = [System.Threading.ApartmentState]::STA
    $rs.Open()
    $ps = [powershell]::Create()
    $ps.Runspace = $rs
    [void]$ps.AddScript($picker).AddArgument($Root)
    try {
        $out = $ps.Invoke()
        foreach ($e in $ps.Streams.Error) {
            Write-Host $e -ForegroundColor Red
        }
        if ($out -and $out.Count -gt 0) {
            return [string]$out[-1]
        }
    }
    finally {
        $rs.Close()
        $ps.Dispose()
    }
    return [string]::Empty
}

$condaActivateCandidates = @(
    "D:\anaconda\Scripts\activate.bat",
    "C:\ProgramData\anaconda3\Scripts\activate.bat",
    "$env:USERPROFILE\anaconda3\Scripts\activate.bat",
    "$env:USERPROFILE\miniconda3\Scripts\activate.bat"
)
$condaActivateBat = $condaActivateCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ([string]::IsNullOrWhiteSpace($CsvPath)) {
    try {
        $picked = Get-CsvPathViaOpenFileDialogSta -Root $projectRoot
        if ([string]::IsNullOrWhiteSpace($picked)) {
            Write-Host 'No file selected. Exiting.' -ForegroundColor Yellow
            exit 0
        }
        $CsvPath = $picked
    }
    catch {
        Write-Host 'Could not open file dialog. Type the full path to driving_data.csv:' -ForegroundColor Yellow
        $CsvPath = Read-Host
    }
}

$CsvPath = $CsvPath.Trim().Trim('"')

if (-not (Test-Path -LiteralPath $CsvPath)) {
    if ([System.IO.Path]::IsPathRooted($CsvPath)) {
        Write-Host "CSV not found: $CsvPath" -ForegroundColor Red
        exit 1
    }
    $tryJoin = Join-Path $projectRoot $CsvPath
    if (Test-Path -LiteralPath $tryJoin) {
        $CsvPath = $tryJoin
    }
    else {
        Write-Host "CSV not found: $CsvPath" -ForegroundColor Red
        exit 1
    }
}

$minimumScreensForLayout = 4
$screenCount = 1
try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    $screenCount = [System.Windows.Forms.Screen]::AllScreens.Count
}
catch {
    $screenCount = 1
}
$useMultiDisplayLayout = $ForceMultiDisplay -or ($screenCount -ge $minimumScreensForLayout)

$dMain = 2
$dLeft = 1
$dRight = 3
$dBack = 1
$dLb = 0
$dRb = 2
if (-not $useMultiDisplayLayout) {
    Write-Host "Displays: $screenCount (need $minimumScreensForLayout for multi-screen layout). Using --display 0 for all windows." -ForegroundColor Yellow
    $dMain = $dLeft = $dRight = $dBack = $dLb = $dRb = 0
}

Write-Host "Resolved CSV: $CsvPath" -ForegroundColor DarkGray
Write-Host "Pygame display indices - main:$dMain left:$dLeft right:$dRight back:$dBack leftBack:$dLb rightBack:$dRb (screens detected: $screenCount)" -ForegroundColor DarkGray

# Use absolute quoted paths so cmd.exe after conda activate still runs the replay script (not the CSV as Python input).
$replayPyFile = if ($ReplayMode -eq 'L3') {
    Join-Path $projectRoot 'tools\replay_trajectory_l3.py'
} else {
    Join-Path $projectRoot 'tools\replay_trajectory.py'
}
$replayCmd = "python `"$replayPyFile`" `"$CsvPath`" --host $CarlaHost --port $CarlaPort --res 1920x1080 --display $dMain --snap-to-road --z-smooth-alpha 0.2 --z-smooth-max-step 0.06"

$cameraJobs = @(
    @{
        Title   = "CARLA Replay Left Camera"
        Command = "python .\cameras\Left.py --host $CarlaHost --port $CarlaPort --display $dLeft --rebind-interval 0.2"
    },
    @{
        Title   = "CARLA Replay Right Camera"
        Command = "python .\cameras\Right.py --host $CarlaHost --port $CarlaPort --display $dRight --rebind-interval 0.2"
    },
    @{
        Title   = "CARLA Replay Back Camera"
        Command = "python .\cameras\Back.py --host $CarlaHost --port $CarlaPort --display $dBack --pos-x 832 --pos-y 20 --rebind-interval 0.2"
    },
    @{
        Title   = "CARLA Replay LeftBack Camera"
        Command = "python .\cameras\LeftBack.py --host $CarlaHost --port $CarlaPort --display $dLb --pos-x 975 --pos-y 700 --rebind-interval 0.2"
    },
    @{
        Title   = "CARLA Replay RightBack Camera"
        Command = "python .\cameras\RightBack.py --host $CarlaHost --port $CarlaPort --display $dRb --pos-x 975 --pos-y 760 --rebind-interval 0.2"
    }
)

function Start-CmdJob {
    param($Title, $Command)
    # 单引号格式串，避免 PowerShell 7+ 将双引号串内的 && 解析为语句分隔符
    if ($condaActivateBat) {
        $cmdLine = 'title {0} && cd /d "{1}" && call "{2}" {3} && {4}' -f $Title, $projectRoot, $condaActivateBat, $condaEnvName, $Command
    }
    else {
        $cmdLine = 'title {0} && cd /d "{1}" && conda activate {2} && {3}' -f $Title, $projectRoot, $condaEnvName, $Command
    }
    Start-Process -FilePath "cmd.exe" -ArgumentList @('/k', $cmdLine) | Out-Null
}

Write-Host "Starting replay main window ($ReplayMode, ensure CARLA is running)..." -ForegroundColor Cyan
$replayTitle = if ($ReplayMode -eq 'L3') { 'CARLA Replay Main View (L3)' } else { 'CARLA Replay Main View (L4)' }
Start-CmdJob -Title $replayTitle -Command $replayCmd

Write-Host "Waiting ${CameraStartupDelaySec}s for hero vehicle, then starting camera windows..." -ForegroundColor Yellow
Start-Sleep -Seconds $CameraStartupDelaySec

foreach ($job in $cameraJobs) {
    Start-CmdJob -Title $job.Title -Command $job.Command
    Start-Sleep -Milliseconds 300
}

if ($condaActivateBat) {
    Write-Host "Replay + all views started (conda env: $condaEnvName)." -ForegroundColor Green
}
else {
    Write-Host "Replay + all views started. No activate.bat; conda must be on PATH." -ForegroundColor Yellow
}
