@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "start-system"

call "%ROOT%tools\deploy_console.bat" step "[1/5] Checking bundled runtime..."
set "PY="
if exist "%ROOT%runtime\python.exe" set "PY=%ROOT%runtime\python.exe"
if not defined PY if exist "%ROOT%venv\Scripts\python.exe" set "PY=%ROOT%venv\Scripts\python.exe"
if not defined PY goto not_ready
call "%ROOT%tools\deploy_console.bat" ok "Runtime found."

if not defined PORT set "PORT=5000"
set "URL=http://127.0.0.1:%PORT%/"

call "%ROOT%tools\deploy_console.bat" step "[2/5] Checking production dependencies..."
"%PY%" -c "import flask, docx, waitress" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto not_ready
call "%ROOT%tools\deploy_console.bat" ok "Waitress and application dependencies found."

call "%ROOT%tools\deploy_console.bat" step "[3/5] Checking application import and database..."
"%PY%" -c "import app; print(app.__file__)" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Application and database are ready."

call "%ROOT%tools\deploy_console.bat" step "[4/5] Starting production server..."
"%PY%" -c "import urllib.request; urllib.request.urlopen('%URL%', timeout=1)" >nul 2>&1
if not errorlevel 1 goto healthy
start "Camp Management System" /min cmd /d /c ""%PY%" "%ROOT%serve.py" >>"%ROOT%logs\server-console.log" 2>&1"
set /a WAIT=0
:wait_server
timeout /t 1 /nobreak >nul
"%PY%" -c "import urllib.request; urllib.request.urlopen('%URL%', timeout=1)" >nul 2>&1
if not errorlevel 1 goto healthy
set /a WAIT+=1
if !WAIT! LSS 30 goto wait_server
goto failed

:healthy
call "%ROOT%tools\deploy_console.bat" ok "Production server is healthy at %URL%."
call "%ROOT%tools\deploy_console.bat" step "[5/5] Opening browser..."
start "" "%URL%"
call "%ROOT%tools\deploy_console.bat" ok "System is running. Close this launcher window; the server remains active."

endlocal
exit /b 0

:not_ready
call "%ROOT%tools\deploy_console.bat" error "Production runtime is not ready. Run SETUP_OFFLINE.bat first."
endlocal
exit /b 1
:failed
call "%ROOT%tools\deploy_console.bat" error "Server stopped with an error. See logs\start-system.log."
endlocal
exit /b 1
