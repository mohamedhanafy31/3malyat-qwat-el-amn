@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "start-system"

call "%ROOT%tools\deploy_console.bat" step "[1/4] Checking runtime..."
set "PY="
if exist "%ROOT%runtime\python.exe" set "PY=%ROOT%runtime\python.exe"
if not defined PY if exist "%ROOT%venv\Scripts\python.exe" set "PY=%ROOT%venv\Scripts\python.exe"
if not defined PY goto not_ready
call "%ROOT%tools\deploy_console.bat" ok "Runtime found."

call "%ROOT%tools\deploy_console.bat" step "[2/4] Checking application dependencies..."
"%PY%" -c "import flask, docx" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto not_ready
call "%ROOT%tools\deploy_console.bat" ok "Dependencies found."

if not defined PORT set "PORT=5000"
call "%ROOT%tools\deploy_console.bat" step "[3/4] Starting local server on port %PORT%..."
start "" /b cmd /c "timeout /t 2 >nul & start "" http://127.0.0.1:%PORT%"
"%PY%" -c "import waitress" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 (
    call "%ROOT%tools\deploy_console.bat" warn "Waitress is unavailable; using Flask fallback."
    "%PY%" "%ROOT%app.py" >>"%DEPLOY_LOG%" 2>&1
) else (
    "%PY%" "%ROOT%serve.py" >>"%DEPLOY_LOG%" 2>&1
)
if errorlevel 1 goto failed

call "%ROOT%tools\deploy_console.bat" ok "Server stopped cleanly."
endlocal
exit /b 0

:not_ready
call "%ROOT%tools\deploy_console.bat" error "Runtime is not ready. Run SETUP_OFFLINE.bat first."
endlocal
exit /b 1
:failed
call "%ROOT%tools\deploy_console.bat" error "Server stopped with an error. See logs\start-system.log."
endlocal
exit /b 1
