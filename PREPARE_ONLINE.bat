@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "prepare-online"

call "%ROOT%tools\deploy_console.bat" step "[1/4] Checking host Python..."
set "SYSPY="
where python >nul 2>&1 && set "SYSPY=python"
if not defined SYSPY where py >nul 2>&1 && set "SYSPY=py"
if not defined SYSPY goto no_python
call "%ROOT%tools\deploy_console.bat" ok "Host Python found."

call "%ROOT%tools\deploy_console.bat" step "[2/4] Downloading Windows runtime and required files..."
call "%ROOT%tools\deploy_console.bat" info "Internet is required. This can take several minutes."
%SYSPY% "%ROOT%tools\prepare_offline_bundle.py" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Python, wheels, Arabic OCR, and checksums are ready."

call "%ROOT%tools\deploy_console.bat" step "[3/4] Configuring this downloaded project..."
set "PERSONNEL_SETUP_FROM_PREPARE=1"
call "%ROOT%SETUP_OFFLINE.bat"
set "SETUP_RESULT=!ERRORLEVEL!"
set "PERSONNEL_SETUP_FROM_PREPARE="
if not "!SETUP_RESULT!"=="0" goto setup_failed
call "%ROOT%tools\deploy_console.bat" ok "This project folder is configured and verified."

call "%ROOT%tools\deploy_console.bat" step "[4/4] Ready to start..."
call "%ROOT%tools\deploy_console.bat" info "Double-click START_SYSTEM.bat. Future starts do not need internet."
if not defined PERSONNEL_NO_PAUSE pause
endlocal
exit /b 0

:no_python
call "%ROOT%tools\deploy_console.bat" error "Python is required on this online preparation PC."
goto show_failure

:setup_failed
call "%ROOT%tools\deploy_console.bat" error "Downloaded files are ready, but local setup failed."
goto show_failure

:failed
call "%ROOT%tools\deploy_console.bat" error "Preparation failed. See logs\prepare-online.log."
goto show_failure

:show_failure
call "%ROOT%tools\deploy_console.bat" info "Details: %DEPLOY_LOG%"
if not defined PERSONNEL_NO_PAUSE if not defined PERSONNEL_SETUP_FROM_START (
    echo.
    echo Press any key to close this window after reading the error above.
    pause >nul
)
endlocal
exit /b 1
