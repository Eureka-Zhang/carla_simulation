@echo off
REM Double-click: pick CSV in dialog, then start replay + all camera windows.
REM Prefer Windows PowerShell 5.1 (STA by default). If only pwsh exists, the .ps1 uses STA runspace for the file dialog.

cd /d "%~dp0"
set "PSX=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%PSX%" (
  "%PSX%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_all_views.ps1"
)
echo.
pause
