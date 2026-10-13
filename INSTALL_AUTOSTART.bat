@echo off
rem Starts the system hidden at every Windows login and restarts it if it crashes.
rem Usage:  INSTALL_AUTOSTART.bat          install and start now
rem         INSTALL_AUTOSTART.bat remove   stop starting at login
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "install-autostart"

if not defined PORT set "PORT=5000"
set "URL=http://127.0.0.1:%PORT%/"
set "LINK_NAME=Personnel System.lnk"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%STARTUP%" mkdir "%STARTUP%" >nul 2>&1

if /i "%~1"=="remove" goto remove

call "%ROOT%tools\deploy_console.bat" step "[1/3] Checking runtime..."
set "PY="
set "PYW="
if exist "%ROOT%runtime\python.exe" set "PY=%ROOT%runtime\python.exe"
if exist "%ROOT%runtime\pythonw.exe" set "PYW=%ROOT%runtime\pythonw.exe"
if not defined PY if exist "%ROOT%venv\Scripts\python.exe" set "PY=%ROOT%venv\Scripts\python.exe"
if not defined PYW if exist "%ROOT%venv\Scripts\pythonw.exe" set "PYW=%ROOT%venv\Scripts\pythonw.exe"
if not defined PY goto not_ready
if not defined PYW goto not_ready
"%PY%" -c "import flask, docx, waitress" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto not_ready
call "%ROOT%tools\deploy_console.bat" ok "Runtime found."

call "%ROOT%tools\deploy_console.bat" step "[2/3] Adding the system to Windows startup..."
set "LINK=%STARTUP%\%LINK_NAME%"
set "SUPERVISOR=%ROOT%tools\autostart.py"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK); $s.TargetPath=$env:PYW; $s.Arguments='\"'+$env:SUPERVISOR+'\"'; $s.WorkingDirectory=$env:ROOT; $s.Description='Personnel System'; $s.Save()" >>"%DEPLOY_LOG%" 2>&1
if not exist "%LINK%" goto failed
call "%ROOT%tools\deploy_console.bat" ok "The system will start automatically at every login."

call "%ROOT%tools\deploy_console.bat" step "[3/3] Starting the system now..."
"%PY%" -c "import urllib.request; urllib.request.urlopen('%URL%', timeout=1)" >nul 2>&1
if not errorlevel 1 goto healthy
start "" "%PYW%" "%SUPERVISOR%"
set /a WAIT=0
:wait_server
timeout /t 1 /nobreak >nul
"%PY%" -c "import urllib.request; urllib.request.urlopen('%URL%', timeout=1)" >nul 2>&1
if not errorlevel 1 goto healthy
set /a WAIT+=1
if !WAIT! LSS 30 goto wait_server
call "%ROOT%tools\deploy_console.bat" error "Server did not respond. See logs\autostart.log and logs\server.log."
goto done_fail

:healthy
call "%ROOT%tools\deploy_console.bat" ok "System is running at %URL%"
call "%ROOT%tools\deploy_console.bat" info "To stop it (for example before restoring a backup) run STOP_SYSTEM.bat."
goto done_ok

:remove
call "%ROOT%tools\deploy_console.bat" step "Removing the system from Windows startup..."
if exist "%STARTUP%\%LINK_NAME%" del "%STARTUP%\%LINK_NAME%"
call "%ROOT%tools\deploy_console.bat" ok "Removed. The system will no longer start at login. Run STOP_SYSTEM.bat to stop it now."
goto done_ok

:not_ready
call "%ROOT%tools\deploy_console.bat" error "Production runtime is not ready. Run SETUP_OFFLINE.bat first."
goto done_fail
:failed
call "%ROOT%tools\deploy_console.bat" error "Could not create the startup shortcut. See logs\install-autostart.log."
goto done_fail

:done_ok
endlocal
pause
exit /b 0
:done_fail
endlocal
pause
exit /b 1
