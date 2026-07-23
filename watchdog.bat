@echo off
title Teaching Cultivator watchdog
cd /d "%~dp0"

REM Prefer `py -3`; fall back to python on PATH
set "PY=py -3"
%PY% -c "import sys" 2>nul || set "PY=python"

echo [%date% %time%] watchdog start
echo cwd: %CD%
echo.

:loop
echo [%date% %time%] starting main.py ...

REM Do not delete data\run.lock — main.py uses mutex + PID to detect duplicates

%PY% main.py
set EXITCODE=%ERRORLEVEL%

echo [%date% %time%] main.py exited (code=%EXITCODE%), restart in 10s...
echo.
timeout /t 10 /nobreak >nul
goto loop
