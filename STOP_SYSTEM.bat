@echo off
rem Stops this Personnel System instance after confirming its readiness marker.
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "stop-system"

set "PY="
if exist "%ROOT%runtime\python.exe" set "PY=%ROOT%runtime\python.exe"
if not defined PY if exist "%ROOT%venv\Scripts\python.exe" set "PY=%ROOT%venv\Scripts\python.exe"
if not defined PY goto no_runtime
if not defined PORT (
    "%PY%" "%ROOT%tools\deploy_check.py" saved-port --file "%ROOT%logs\server.port" >"%ROOT%logs\stop-port.tmp"
    if not errorlevel 1 set /p PORT=<"%ROOT%logs\stop-port.tmp"
    del /q "%ROOT%logs\stop-port.tmp" >nul 2>&1
)
if not defined PORT set "PORT=5000"
if defined PY (
    "%PY%" "%ROOT%tools\deploy_check.py" ready --port "%PORT%" --timeout 1 --quiet
    set "READY_RESULT=!ERRORLEVEL!"
    if "!READY_RESULT!"=="10" goto not_running
    if "!READY_RESULT!"=="12" goto foreign_port
    if "!READY_RESULT!"=="13" goto foreign_port
)

call "%ROOT%tools\deploy_console.bat" step "[1/1] Stopping the server on port %PORT%..."
set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /c:":%PORT% " ^| findstr LISTENING') do (
    set "FOUND=1"
    taskkill /F /PID %%P >>"%DEPLOY_LOG%" 2>&1
)
if not defined FOUND goto not_running
timeout /t 2 /nobreak >nul
netstat -ano | findstr /c:":%PORT% " | findstr LISTENING >nul
if not errorlevel 1 (
    call "%ROOT%tools\deploy_console.bat" error "The server is still running. See logs\stop-system.log."
    endlocal
    pause
    exit /b 1
)
call "%ROOT%tools\deploy_console.bat" ok "System stopped. Run START_SYSTEM.bat whenever you want to start it again."

goto done

:not_running
call "%ROOT%tools\deploy_console.bat" ok "The system was not running."
goto done

:foreign_port
call "%ROOT%tools\deploy_console.bat" error "Port %PORT% is not confirmed as this Personnel System. Nothing was killed."
call "%ROOT%tools\deploy_console.bat" info "Close the other program yourself, or set PORT to the Personnel System port and retry."
endlocal
pause
exit /b 1

:no_runtime
call "%ROOT%tools\deploy_console.bat" error "No configured Personnel System runtime was found. Nothing was killed."
call "%ROOT%tools\deploy_console.bat" info "Run SETUP_OFFLINE.bat first, or stop the intended process manually after confirming its identity."
endlocal
pause
exit /b 1

:done
endlocal
pause
exit /b 0
