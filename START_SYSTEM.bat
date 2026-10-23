@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHONUTF8=1"
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
"%PY%" -c "import flask, docx, openpyxl, waitress" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto not_ready
call "%ROOT%tools\deploy_console.bat" ok "Waitress and application dependencies found."

set "TESSERACT_CMD=%ROOT%tools\tesseract\tesseract.exe"
set "TESSDATA_PREFIX=%ROOT%tools\tesseract\tessdata"
if not exist "%TESSERACT_CMD%" (
    set "TESSERACT_CMD=%ProgramFiles%\Tesseract-OCR\tesseract.exe"
    set "TESSDATA_PREFIX=%ProgramFiles%\Tesseract-OCR\tessdata"
)
if not exist "%TESSERACT_CMD%" goto not_ready
if not exist "%TESSDATA_PREFIX%\ara.traineddata" goto not_ready

call "%ROOT%tools\deploy_console.bat" step "[3/5] Checking application import and database..."
"%PY%" -c "import app; print(app.__file__)" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Application and database are ready."

call "%ROOT%tools\deploy_console.bat" step "[4/5] Starting production server..."
"%PY%" -c "import urllib.request; urllib.request.urlopen('%URL%', timeout=1)" >nul 2>&1
if not errorlevel 1 goto healthy
set "PYW=%PY%"
if exist "%ROOT%runtime\pythonw.exe" set "PYW=%ROOT%runtime\pythonw.exe"
if exist "%ROOT%venv\Scripts\pythonw.exe" set "PYW=%ROOT%venv\Scripts\pythonw.exe"
start "" /b "%PYW%" "%ROOT%serve.py" >>"%ROOT%logs\server-console.log" 2>&1
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
goto show_failure
:failed
call "%ROOT%tools\deploy_console.bat" error "Server stopped with an error. See logs\start-system.log."
goto show_failure

:show_failure
call "%ROOT%tools\deploy_console.bat" info "Details: %DEPLOY_LOG%"
call "%ROOT%tools\deploy_console.bat" info "Server output: %ROOT%logs\server-console.log"
if not defined PERSONNEL_NO_PAUSE (
    echo.
    echo Press any key to close this window after reading the error above.
    pause >nul
)
endlocal
exit /b 1
