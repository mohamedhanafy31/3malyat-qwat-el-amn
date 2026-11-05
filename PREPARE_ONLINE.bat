@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHONUTF8=1"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "prepare-online"

call "%ROOT%tools\deploy_console.bat" step "[1/6] Checking host Python..."
set "SYSPY="
for %%C in ("py -3" "python" "py") do if not defined SYSPY (
    %%~C "%ROOT%tools\deploy_check.py" host-python >>"%DEPLOY_LOG%" 2>&1
    if not errorlevel 1 set "SYSPY=%%~C"
)
if not defined SYSPY goto no_python
call "%ROOT%tools\deploy_console.bat" ok "Host Python found: !SYSPY!"

%SYSPY% "%ROOT%tools\deploy_check.py" retire-autostart >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto legacy_autostart_failed

call "%ROOT%tools\deploy_console.bat" step "[2/6] Checking this PC (Windows x64, folders, disk space, running server)..."
set "PRE_OUT=%ROOT%logs\preflight-output.tmp"
%SYSPY% "%ROOT%tools\deploy_check.py" preflight --mode prepare >"!PRE_OUT!" 2>&1
set "PRE_RESULT=!ERRORLEVEL!"
type "!PRE_OUT!"
type "!PRE_OUT!" >>"%DEPLOY_LOG%"
del "!PRE_OUT!" >nul 2>&1
if not "!PRE_RESULT!"=="0" goto preflight_failed

call "%ROOT%tools\deploy_console.bat" step "[3/6] Downloading Windows runtime and required files..."
call "%ROOT%tools\deploy_console.bat" info "Internet is required. This can take several minutes. The previous runtime is kept until the new one is verified."
call "%ROOT%tools\deploy_console.bat" info "Every download, size, checksum and retry is shown below and saved in %DEPLOY_LOG%."
rem The helper prints to the console AND appends to %DEPLOY_LOG% itself, so it is not redirected here.
%SYSPY% "%ROOT%tools\prepare_offline_bundle.py"
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Python, wheels, Tesseract files, Indra models, and checksums are ready."

call "%ROOT%tools\deploy_console.bat" step "[4/6] Configuring this downloaded project..."
set "PERSONNEL_SETUP_FROM_PREPARE=1"
call "%ROOT%SETUP_OFFLINE.bat"
set "SETUP_RESULT=!ERRORLEVEL!"
set "PERSONNEL_SETUP_FROM_PREPARE="
if not "!SETUP_RESULT!"=="0" goto setup_failed
call "%ROOT%tools\deploy_console.bat" ok "This project folder is configured and verified."

call "%ROOT%tools\deploy_console.bat" step "[5/6] Testing Indra OCR for real (loading the models and reading a test image)..."
set "APP_PY=%ROOT%runtime\python.exe"
if not exist "!APP_PY!" set "APP_PY=%ROOT%venv\Scripts\python.exe"
"!APP_PY!" "%ROOT%tools\ocr_setup.py" indra-check
if errorlevel 1 goto indra_check_failed
call "%ROOT%tools\deploy_console.bat" ok "Indra OCR is ready: models load and a real image was read."
goto indra_check_done
:indra_check_failed
call "%ROOT%tools\deploy_console.bat" warn "Indra OCR is NOT ready on this PC. The system still works; photo import uses the weaker fallback engine. Read the lines above, or send logs\prepare-online.log."
:indra_check_done

call "%ROOT%tools\deploy_console.bat" step "[6/6] Ready to start..."
call "%ROOT%tools\deploy_console.bat" info "Double-click START_SYSTEM.bat. Future starts do not need internet."
call "%ROOT%tools\deploy_console.bat" info "To update later: run STOP_SYSTEM.bat, update the files, then run PREPARE_ONLINE.bat again."
call "%ROOT%tools\deploy_console.bat" info "This script prepares the cloned project in place; it does not create a release ZIP."
if not defined PERSONNEL_NO_PAUSE pause
endlocal
exit /b 0

:no_python
call "%ROOT%tools\deploy_console.bat" error "No usable host Python was found on this online preparation PC."
call "%ROOT%tools\deploy_console.bat" info "Install Python 3.9 or newer (64-bit) from python.org with pip enabled, then run this file again."
call "%ROOT%tools\deploy_console.bat" info "The Microsoft Store python.exe shortcut does not work. Check with: py -3 -m pip --version"
goto show_failure

:preflight_failed
call "%ROOT%tools\deploy_console.bat" error "This PC cannot be prepared yet. Fix the problem listed above and run this file again."
goto show_failure

:legacy_autostart_failed
call "%ROOT%tools\deploy_console.bat" error "The old background autostart could not be disabled."
call "%ROOT%tools\deploy_console.bat" info "Restart Windows, then run PREPARE_ONLINE.bat again. Normal startup uses START_SYSTEM.bat only."
goto show_failure

:setup_failed
call "%ROOT%tools\deploy_console.bat" error "Downloaded files are ready, but local setup failed."
goto show_failure

:failed
call "%ROOT%tools\deploy_console.bat" error "Preparation failed. The previous runtime (if any) was kept. See logs\prepare-online.log."
goto show_failure

:show_failure
call "%ROOT%tools\deploy_console.bat" failures
call "%ROOT%tools\deploy_console.bat" info "Details: %DEPLOY_LOG%"
if not defined PERSONNEL_NO_PAUSE if not defined PERSONNEL_SETUP_FROM_START (
    echo.
    echo Press any key to close this window after reading the error above.
    pause >nul
)
endlocal
exit /b 1
