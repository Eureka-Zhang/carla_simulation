@echo off
REM Double-click: CSV file dialog (default browse: phase2\residual_gru_takeover_20s_yaw_shrink_controls), L4 + cameras.
REM For L3 use launch_replay_all_views_l3.bat. Optional args pass through: %*
REM Use Windows PowerShell 5.1 if available (STA). Save this file as ANSI if cmd shows junk characters.

cd /d "%~dp0"
set "PSX=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%PSX%" (
  "%PSX%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1" %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1" %*
)
echo.
pause
