@echo off
REM Double-click: CSV dialog (default browse: phase2\residual_gru_takeover_20s_yaw_shrink_controls), L3 + cameras.
REM Same as launch_replay_all_views_gui.bat but adds -ReplayMode L3.

cd /d "%~dp0"
set "PSX=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%PSX%" (
  "%PSX%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1" -ReplayMode L3 %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1" -ReplayMode L3 %*
)
echo.
pause
