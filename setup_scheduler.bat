@echo off
REM Login autostart via Startup shortcut (no admin required).
REM Optional: ONLOGON scheduled task when run as admin.
REM Push schedule lives in main.py (math / comm / review slots).

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "VBS=%ROOT%\_start_watchdog.vbs"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\teaching-cultivator-bot.lnk"

echo [1/3] Writing Startup shortcut...
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%');" ^
  "$s.TargetPath='wscript.exe'; $s.Arguments='//B \"%VBS%\"';" ^
  "$s.WorkingDirectory='%ROOT%'; $s.WindowStyle=7; $s.Save()"
if exist "%LNK%" (echo   OK: %LNK%) else (echo   FAIL: could not create shortcut & pause & exit /b 1)

echo [2/3] Disable legacy standalone push tasks if present...
schtasks /Change /TN "teaching-cultivator-math" /DISABLE 2>nul
schtasks /Change /TN "teaching-cultivator-comm" /DISABLE 2>nul
schtasks /Change /TN "teaching-cultivator-review" /DISABLE 2>nul

echo [3/3] Try ONLOGON task (ignore failure if no admin)...
schtasks /Create /TN "teaching-cultivator-bot" /TR "wscript.exe //B \"%VBS%\"" /SC ONLOGON /DELAY 0001:00 /RL LIMITED /F 2>nul
if errorlevel 1 (
  echo   Scheduled task not registered. Startup shortcut is enough.
) else (
  echo   OK: teaching-cultivator-bot ONLOGON
)

echo.
echo Done. Next login starts watchdog.bat -^> main.py
echo Manual start: wscript "%VBS%"
echo.
pause
