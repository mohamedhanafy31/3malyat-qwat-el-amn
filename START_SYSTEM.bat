@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHONUTF8=1"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "start-system"

:check_runtime
call "%ROOT%tools\deploy_console.bat" step "[1/5] Checking bundled runtime..."
set "PY="
if exist "%ROOT%runtime\python.exe" set "PY=%ROOT%runtime\python.exe"
if not defined PY if exist "%ROOT%venv\Scripts\python.exe" set "PY=%ROOT%venv\Scripts\python.exe"
if not defined PY goto not_ready
call "%ROOT%tools\deploy_console.bat" ok "Runtime found."

"%PY%" "%ROOT%tools\deploy_check.py" choose-port --range-start 5000 --range-end 5099 --output "%ROOT%logs\server.port"
set "PORT_RESULT=!ERRORLEVEL!"
set "SERVER_STATE=new"
if "!PORT_RESULT!"=="20" set "SERVER_STATE=ready"
if "!PORT_RESULT!"=="21" set "SERVER_STATE=unavailable"
if not "!PORT_RESULT!"=="0" if not "!PORT_RESULT!"=="20" if not "!PORT_RESULT!"=="21" goto port_selection_failed
set /p PORT=<"%ROOT%logs\server.port"
set "URL=http://127.0.0.1:%PORT%/"

call "%ROOT%tools\deploy_console.bat" step "[2/5] Checking production dependencies..."
"%PY%" -c "import flask, docx, openpyxl, waitress" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto not_ready
call "%ROOT%tools\deploy_console.bat" ok "Waitress and application dependencies found."

if exist "%ROOT%tools\tesseract\tessdata\ara.traineddata" set "TESSDATA_PREFIX=%ROOT%tools\tesseract\tessdata"
"%PY%" "%ROOT%tools\ocr_setup.py" status --quiet >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 call "%ROOT%tools\deploy_console.bat" warn "Optional image OCR is unavailable; the rest of the system will still start."

call "%ROOT%tools\deploy_console.bat" step "[3/5] Checking application import and database..."
"%PY%" "%ROOT%tools\offline_env.py" check-data --quiet >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto data_failed
"%PY%" -c "import app; print(app.__file__)" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Application and database are ready."

call "%ROOT%tools\deploy_console.bat" step "[4/5] Starting production server..."
if "!SERVER_STATE!"=="ready" goto healthy
if "!SERVER_STATE!"=="unavailable" goto readiness_failed
set "PYW=%PY%"
if exist "%ROOT%runtime\pythonw.exe" set "PYW=%ROOT%runtime\pythonw.exe"
if exist "%ROOT%venv\Scripts\pythonw.exe" set "PYW=%ROOT%venv\Scripts\pythonw.exe"
>>"%DEPLOY_LOG%" echo [%date% %time%] [TRACE] Launching serve.py with port %PORT%.
start "" /b "%PYW%" "%ROOT%serve.py" >>"%ROOT%logs\server-console.log" 2>&1
call "%ROOT%tools\deploy_console.bat" info "Server process launched. Waiting up to 30 seconds for readiness..."
set /a WAIT=0
:wait_server
timeout /t 1 /nobreak >nul
"%PY%" "%ROOT%tools\deploy_check.py" ready --port "%PORT%" --timeout 1 --quiet --trace >>"%DEPLOY_LOG%" 2>&1
set "READY_RESULT=!ERRORLEVEL!"
if "!READY_RESULT!"=="0" goto healthy
if "!READY_RESULT!"=="11" goto readiness_failed
set /a WAIT+=1
if !WAIT! LSS 30 goto wait_server
if "!READY_RESULT!"=="12" goto port_failed
goto failed

:healthy
call "%ROOT%tools\deploy_console.bat" ok "Production server is healthy at %URL%."
call "%ROOT%tools\deploy_console.bat" step "[5/5] Opening browser..."
start "" "%URL%"
call "%ROOT%tools\deploy_console.bat" ok "System is running. Close this launcher window; the server remains active."

endlocal
exit /b 0

:not_ready
if defined AUTO_SETUP_ATTEMPTED goto setup_failed
set "AUTO_SETUP_ATTEMPTED=1"
call "%ROOT%tools\deploy_console.bat" info "First launch detected. Running offline setup automatically..."
set "PERSONNEL_SETUP_FROM_START=1"
call "%ROOT%SETUP_OFFLINE.bat"
set "SETUP_RESULT=!ERRORLEVEL!"
set "PERSONNEL_SETUP_FROM_START="
if not "!SETUP_RESULT!"=="0" goto setup_failed
call "%ROOT%tools\deploy_console.bat" ok "First-launch setup completed. Continuing startup."
goto check_runtime

:setup_failed
call "%ROOT%tools\deploy_console.bat" error "Automatic offline setup failed."
goto show_failure
:failed
call "%ROOT%tools\deploy_console.bat" error "Server did not become ready within 30 seconds. See logs\start-system.log and logs\server.log."
goto show_failure
:data_failed
call "%ROOT%tools\deploy_console.bat" error "The real application data failed validation. No data was changed."
goto show_failure
:readiness_failed
call "%ROOT%tools\deploy_console.bat" error "The Personnel System answered, but its data is unavailable. See logs\server.log."
goto show_failure
:port_failed
call "%ROOT%tools\deploy_console.bat" error "Port %PORT% answered as a different application after launch. See the trace in logs\start-system.log."
goto show_failure
:port_selection_failed
call "%ROOT%tools\deploy_console.bat" error "No available server port was found from 5000 through 5099."
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
