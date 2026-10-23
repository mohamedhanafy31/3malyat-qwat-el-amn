@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "prepare-online"

call "%ROOT%tools\deploy_console.bat" step "[1/3] Checking host Python..."
set "SYSPY="
where python >nul 2>&1 && set "SYSPY=python"
if not defined SYSPY where py >nul 2>&1 && set "SYSPY=py"
if not defined SYSPY goto no_python
call "%ROOT%tools\deploy_console.bat" ok "Host Python found."

call "%ROOT%tools\deploy_console.bat" step "[2/3] Building complete Windows offline bundle..."
%SYSPY% "%ROOT%tools\prepare_offline_bundle.py" --archive >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Python, wheels, Arabic OCR, checksums, and ZIP are ready."

call "%ROOT%tools\deploy_console.bat" step "[3/3] Showing release location..."
call "%ROOT%tools\deploy_console.bat" info "Copy the ZIP from dist to the offline PC, extract it, then run SETUP_OFFLINE.bat."
endlocal
exit /b 0

:no_python
call "%ROOT%tools\deploy_console.bat" error "Python is required on this online preparation PC."
endlocal
exit /b 1

:failed
call "%ROOT%tools\deploy_console.bat" error "Preparation failed. See logs\prepare-online.log."
endlocal
exit /b 1
