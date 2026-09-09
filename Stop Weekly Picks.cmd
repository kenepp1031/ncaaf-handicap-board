@echo off
title Stop College Football Picks
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 dashboard.py --stop
    goto done
)
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" dashboard.py --stop
    goto done
)
python dashboard.py --stop
:done
timeout /t 3 >nul
