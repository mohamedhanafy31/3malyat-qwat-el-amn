@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "backups"

set "PY="
if exist "%ROOT%runtime\python.exe" set "PY=%ROOT%runtime\python.exe"
if not defined PY if exist "%ROOT%venv\Scripts\python.exe" set "PY=%ROOT%venv\Scripts\python.exe"
if not defined PY goto not_ready

:menu
cls
call "%ROOT%tools\deploy_console.bat" info "Backup Manager"
call "%ROOT%tools\deploy_console.bat" info "[1] List backups"
call "%ROOT%tools\deploy_console.bat" info "[2] Verify backups"
call "%ROOT%tools\deploy_console.bat" info "[3] Restore latest valid backup"
call "%ROOT%tools\deploy_console.bat" info "[4] Restore a named backup"
call "%ROOT%tools\deploy_console.bat" info "[5] Exit"
call "%ROOT%tools\deploy_console.bat" info "Awaiting selection."
set "choice="
set /p "choice=Select an option: "
if "%choice%"=="1" goto list
if "%choice%"=="2" goto verify
if "%choice%"=="3" goto latest
if "%choice%"=="4" goto named
if "%choice%"=="5" goto done
goto menu

:list
call "%ROOT%tools\deploy_console.bat" step "Listing backups..."
"%PY%" "%ROOT%tools\backup.py" list --english >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 (call "%ROOT%tools\deploy_console.bat" error "Backup listing failed.") else (call "%ROOT%tools\deploy_console.bat" ok "Backup list written to logs\backups.log.")
pause
goto menu

:verify
call "%ROOT%tools\deploy_console.bat" step "Verifying backups..."
"%PY%" "%ROOT%tools\backup.py" verify --english >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 (call "%ROOT%tools\deploy_console.bat" error "One or more backups are invalid. See logs\backups.log.") else (call "%ROOT%tools\deploy_console.bat" ok "All backups are valid.")
pause
goto menu

:latest
call "%ROOT%tools\deploy_console.bat" warn "Stop the application before restoring data."
set "confirm="
set /p "confirm=Type RESTORE to continue: "
if /i not "%confirm%"=="RESTORE" (call "%ROOT%tools\deploy_console.bat" warn "Restore cancelled." & pause & goto menu)
"%PY%" "%ROOT%tools\backup.py" restore --latest --yes --english >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 (call "%ROOT%tools\deploy_console.bat" error "Restore failed. See logs\backups.log.") else (call "%ROOT%tools\deploy_console.bat" ok "Latest valid backup restored.")
pause
goto menu

:named
set "bname="
set /p "bname=Enter the exact backup filename: "
if not defined bname goto menu
call "%ROOT%tools\deploy_console.bat" warn "Stop the application before restoring data."
set "confirm="
set /p "confirm=Type RESTORE to continue: "
if /i not "%confirm%"=="RESTORE" (call "%ROOT%tools\deploy_console.bat" warn "Restore cancelled." & pause & goto menu)
"%PY%" "%ROOT%tools\backup.py" restore "%bname%" --yes --english >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 (call "%ROOT%tools\deploy_console.bat" error "Restore failed. See logs\backups.log.") else (call "%ROOT%tools\deploy_console.bat" ok "Backup restored.")
pause
goto menu

:not_ready
call "%ROOT%tools\deploy_console.bat" error "Runtime is not ready. Run SETUP_OFFLINE.bat first."
endlocal
exit /b 1
:done
endlocal
exit /b 0
