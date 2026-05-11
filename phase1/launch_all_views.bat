@echo off
REM Main experiment multi-view (car_following_experiment + cameras).
REM Trajectory replay: launch_replay_all_views_gui.bat (L4) or launch_replay_all_views_l3.bat (L3).
setlocal

set SCRIPT_DIR=%~dp0
powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%launch_all_views.ps1"

endlocal
