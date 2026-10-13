@echo off
rem Parsifal: platform availability check. Double-click to run.
chcp 65001 >nul
cd /d "%~dp0"
title Parsifal - platform check

where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% -X utf8 check_platforms.py %*

echo.
pause
