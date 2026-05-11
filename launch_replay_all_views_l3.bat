@echo off
REM Double-click: file dialog, then L3 replay + cameras (tools/replay_trajectory_l3.py).
REM Same as launch_replay_all_views_gui.bat but adds -ReplayMode L3.

cd /d "%~dp0"
set "PSX=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%PSX%" (
  "%PSX%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1" -ReplayMode L3
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1" -ReplayMode L3
)
echo.
pause
