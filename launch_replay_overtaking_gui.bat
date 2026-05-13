@echo off
REM Double-click: folder picker opens at phase2\overtaking_p4_return_fix (you still choose the folder), then overtaking replay + cameras.
REM Uses launch_replay_overtaking_gui.ps1 (STA folder dialog). Save as ANSI if cmd shows junk characters.

cd /d "%~dp0"
set "PSX=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%PSX%" (
  "%PSX%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_overtaking_gui.ps1" %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_replay_overtaking_gui.ps1" %*
)
echo.
pause
