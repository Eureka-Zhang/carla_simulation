@echo off
REM Double-click: file dialog, then L4 replay + cameras (tools/replay_trajectory.py).
REM For L3 use launch_replay_all_views_l3.bat in this folder.
REM Use Windows PowerShell 5.1 if available (STA). Save this file as ANSI if cmd shows junk characters.

cd /d "%~dp0"
set "PSX=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%PSX%" (
  "%PSX%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1"
)
echo.
pause
