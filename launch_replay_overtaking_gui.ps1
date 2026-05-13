# Overtaking replay + multi-camera views (same layout as launch_replay_all_views.ps1)
# Pick root folder (*exp1_o / *exp2_o / *exp3_o with driving_data.csv), then tools/replay_trajectory_overtaking.py + cameras/*.py
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\launch_replay_overtaking_gui.ps1
#   powershell -ExecutionPolicy Bypass -File .\launch_replay_overtaking_gui.ps1 -OvertakeRoot "E:\data\my_run"
#
# Double-click: launch_replay_overtaking_gui.bat
#
# Optional: -CarlaHost / -CarlaPort / -CameraStartupDelaySec / -HoldFirstFrameSec / -InitialBrowseFolder
# When -OvertakeRoot is omitted, a folder picker is shown. It opens at phase2\overtaking_p4_return_fix (or -InitialBrowseFolder) via Shell BrowseForFolder, not WinForms SelectedPath (unreliable).
# Multi-display: see below.

param(
    [Parameter(Mandatory = $false)]
    [string]$OvertakeRoot = '',
    [string]$InitialBrowseFolder = '',
    [string]$CarlaHost = '127.0.0.1',
    [int]$CarlaPort = 2000,
    [double]$CameraStartupDelaySec = 1.5,
    [double]$HoldFirstFrameSec = 10.0,
    [switch]$ForceMultiDisplay
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$condaEnvName = 'carla39'

function Get-OvertakeRootViaFolderDialogSta {
    param([string]$Root)
    $picker = {
        param([string]$R)
        $desc = 'Select folder that contains subfolders exp1_o, exp2_o, exp3_o (each with driving_data.csv)'
        # BIF_RETURNONLYFSDIRS (0x1) | BIF_NEWDIALOGSTYLE (0x40): folder-only, Vista-style tree.
        # 4th arg is the browse start path (WinForms FolderBrowserDialog.SelectedPath often does not open there).
        $flags = [int]0x41
        $start = ''
        if (Test-Path -LiteralPath $R) {
            $start = [System.IO.Path]::GetFullPath($R)
        }
        else {
            $start = [System.IO.Path]::GetFullPath([Environment]::GetFolderPath('Desktop'))
        }
        $shell = $null
        $folder = $null
        try {
            $shell = New-Object -ComObject Shell.Application
            $folder = $shell.BrowseForFolder(0, $desc, $flags, $start)
            if ($null -eq $folder) {
                return [string]::Empty
            }
            return [string]$folder.Self.Path
        }
        finally {
            if ($null -ne $folder) {
                [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($folder)
            }
            if ($null -ne $shell) {
                [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
            }
        }
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
    'D:\anaconda\Scripts\activate.bat',
    'C:\ProgramData\anaconda3\Scripts\activate.bat',
    "$env:USERPROFILE\anaconda3\Scripts\activate.bat",
    "$env:USERPROFILE\miniconda3\Scripts\activate.bat"
)
$condaActivateBat = $condaActivateCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ([string]::IsNullOrWhiteSpace($OvertakeRoot)) {
    try {
        $defaultOvertakeFolder = Join-Path $projectRoot 'phase2\overtaking_p4_return_fix'
        $dlgRoot = if (-not [string]::IsNullOrWhiteSpace($InitialBrowseFolder)) {
            $InitialBrowseFolder.Trim().Trim('"')
        }
        else {
            $defaultOvertakeFolder
        }
        if (-not (Test-Path -LiteralPath $dlgRoot -PathType Container)) {
            $dlgRoot = $projectRoot
        }
        $picked = Get-OvertakeRootViaFolderDialogSta -Root $dlgRoot
        if ([string]::IsNullOrWhiteSpace($picked)) {
            Write-Host 'No folder selected. Exiting.' -ForegroundColor Yellow
            exit 0
        }
        $OvertakeRoot = $picked
    }
    catch {
        Write-Host 'Could not open folder dialog. Paste full path to overtaking root folder:' -ForegroundColor Yellow
        $OvertakeRoot = Read-Host
    }
}

$OvertakeRoot = $OvertakeRoot.Trim().Trim('"')

if (-not (Test-Path -LiteralPath $OvertakeRoot -PathType Container)) {
    if (-not [System.IO.Path]::IsPathRooted($OvertakeRoot)) {
        $tryJoin = Join-Path $projectRoot $OvertakeRoot
        if (Test-Path -LiteralPath $tryJoin -PathType Container) {
            $OvertakeRoot = $tryJoin
        }
    }
}
if (-not (Test-Path -LiteralPath $OvertakeRoot -PathType Container)) {
    Write-Host "Folder not found: $OvertakeRoot" -ForegroundColor Red
    exit 1
}

$OvertakeRoot = (Resolve-Path -LiteralPath $OvertakeRoot).Path
$replayPy = Join-Path $projectRoot 'tools\replay_trajectory_overtaking.py'
if (-not (Test-Path -LiteralPath $replayPy)) {
    Write-Host "Script not found: $replayPy" -ForegroundColor Red
    exit 1
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

Write-Host "Overtake root: $OvertakeRoot" -ForegroundColor DarkGray
Write-Host "Pygame display indices - main:$dMain left:$dLeft right:$dRight back:$dBack leftBack:$dLb rightBack:$dRb (screens detected: $screenCount)" -ForegroundColor DarkGray

$hold = [string]$HoldFirstFrameSec -replace ',', '.'
$replayCmd = "python `"$replayPy`" `"$OvertakeRoot`" --host $CarlaHost --port $CarlaPort --res 1920x1080 --display $dMain --snap-to-road --z-smooth-alpha 0.2 --z-smooth-max-step 0.06 --hold-first-frame-s $hold --pre-start-countdown-s 0 --playback-start-sim-offset-s 0"

$cameraJobs = @(
    @{
        Title   = 'CARLA Overtaking Replay Left Camera'
        Command = "python .\cameras\Left.py --host $CarlaHost --port $CarlaPort --display $dLeft --rebind-interval 0.2"
    },
    @{
        Title   = 'CARLA Overtaking Replay Right Camera'
        Command = "python .\cameras\Right.py --host $CarlaHost --port $CarlaPort --display $dRight --rebind-interval 0.2"
    },
    @{
        Title   = 'CARLA Overtaking Replay Back Camera'
        Command = "python .\cameras\Back.py --host $CarlaHost --port $CarlaPort --display $dBack --pos-x 832 --pos-y 20 --rebind-interval 0.2"
    },
    @{
        Title   = 'CARLA Overtaking Replay LeftBack Camera'
        Command = "python .\cameras\LeftBack.py --host $CarlaHost --port $CarlaPort --display $dLb --pos-x 975 --pos-y 700 --rebind-interval 0.2"
    },
    @{
        Title   = 'CARLA Overtaking Replay RightBack Camera'
        Command = "python .\cameras\RightBack.py --host $CarlaHost --port $CarlaPort --display $dRb --pos-x 975 --pos-y 760 --rebind-interval 0.2"
    }
)

function Start-CmdJob {
    param($Title, $Command)
    if ($condaActivateBat) {
        $cmdLine = 'title {0} && cd /d "{1}" && call "{2}" {3} && {4}' -f $Title, $projectRoot, $condaActivateBat, $condaEnvName, $Command
    }
    else {
        $cmdLine = 'title {0} && cd /d "{1}" && conda activate {2} && {3}' -f $Title, $projectRoot, $condaEnvName, $Command
    }
    Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', $cmdLine) | Out-Null
}

Write-Host 'Starting overtaking replay main window (ensure CARLA is running)...' -ForegroundColor Cyan
Start-CmdJob -Title 'CARLA Overtaking Replay Main (exp1_o exp2_o exp3_o)' -Command $replayCmd

Write-Host "Waiting ${CameraStartupDelaySec}s for hero vehicle, then starting camera windows..." -ForegroundColor Yellow
Start-Sleep -Seconds $CameraStartupDelaySec

foreach ($job in $cameraJobs) {
    Start-CmdJob -Title $job.Title -Command $job.Command
    Start-Sleep -Milliseconds 300
}

if ($condaActivateBat) {
    Write-Host "Overtaking replay + all views started (conda env: $condaEnvName)." -ForegroundColor Green
}
else {
    Write-Host 'Overtaking replay + all views started. No activate.bat; conda must be on PATH.' -ForegroundColor Yellow
}
