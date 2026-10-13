@echo off
rem Stops the running system cleanly, including the auto-restart supervisor.
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "stop-system"

if not defined PORT set "PORT=5000"

call "%ROOT%tools\deploy_console.bat" step "[1/2] Telling the auto-restart supervisor to stop..."
>"%ROOT%logs\autostart.stop" echo stop
call "%ROOT%tools\deploy_console.bat" ok "Stop requested."

call "%ROOT%tools\deploy_console.bat" step "[2/2] Stopping the server on port %PORT%..."
set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /c:":%PORT% " ^| findstr LISTENING') do (
    set "FOUND=1"
    taskkill /F /PID %%P >>"%DEPLOY_LOG%" 2>&1
)
if not defined FOUND (
    call "%ROOT%tools\deploy_console.bat" ok "The system was not running."
    goto done
)
timeout /t 2 /nobreak >nul
netstat -ano | findstr /c:":%PORT% " | findstr LISTENING >nul
if not errorlevel 1 (
    call "%ROOT%tools\deploy_console.bat" error "The server is still running. See logs\stop-system.log."
    endlocal
    pause
    exit /b 1
)
call "%ROOT%tools\deploy_console.bat" ok "System stopped. Run START_SYSTEM.bat to start it again; it also starts at the next login if autostart is installed."

:done
endlocal
pause
exit /b 0
