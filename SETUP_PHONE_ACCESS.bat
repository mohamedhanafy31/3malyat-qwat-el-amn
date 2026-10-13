@echo off
rem One-time setup so the Android app can reach this PC from anywhere through Tailscale.
rem Needs internet on this PC and the Tailscale app installed and logged in.
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "setup-phone-access"

if not defined PORT set "PORT=5000"
set "PY="
if exist "%ROOT%runtime\python.exe" set "PY=%ROOT%runtime\python.exe"
if not defined PY if exist "%ROOT%venv\Scripts\python.exe" set "PY=%ROOT%venv\Scripts\python.exe"
if not defined PY goto not_ready

call "%ROOT%tools\deploy_console.bat" step "[1/5] Looking for Tailscale..."
set "TS="
if exist "%ProgramFiles%\Tailscale\tailscale.exe" set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
if not defined TS for /f "delims=" %%T in ('where tailscale 2^>nul') do if not defined TS set "TS=%%T"
if not defined TS goto no_tailscale
call "%ROOT%tools\deploy_console.bat" ok "Tailscale found."

call "%ROOT%tools\deploy_console.bat" step "[2/5] Checking Tailscale login..."
"%TS%" status >nul 2>&1
if not errorlevel 1 goto logged_in
call "%ROOT%tools\deploy_console.bat" info "Not logged in. A browser window will open; log in with the same account as the phone."
"%TS%" up
"%TS%" status >nul 2>&1
if errorlevel 1 goto not_logged_in
:logged_in
call "%ROOT%tools\deploy_console.bat" ok "Logged in."

call "%ROOT%tools\deploy_console.bat" step "[3/5] Keeping Tailscale connected after restarts..."
"%TS%" set --unattended=true >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 (
    call "%ROOT%tools\deploy_console.bat" warn "Could not enable unattended mode. In the Tailscale tray menu, turn on Preferences - Run unattended."
) else (
    call "%ROOT%tools\deploy_console.bat" ok "Tailscale stays connected even before anyone logs in."
)

call "%ROOT%tools\deploy_console.bat" step "[4/5] Publishing the system to your Tailscale devices..."
call "%ROOT%tools\deploy_console.bat" info "If a link appears below, open it, click Enable, and this step continues by itself."
"%TS%" serve --bg %PORT%
if errorlevel 1 goto serve_failed
call "%ROOT%tools\deploy_console.bat" ok "Published (only devices on your Tailscale account can open it)."

call "%ROOT%tools\deploy_console.bat" step "[5/5] Reading the phone address..."
set "PHONE_URL="
for /f "delims=" %%H in ('call "%PY%" "%ROOT%tools\phone_url.py" "%TS%"') do set "PHONE_URL=%%H"
if not defined PHONE_URL goto serve_failed
>"%ROOT%logs\phone-url.txt" echo %PHONE_URL%
call "%ROOT%tools\deploy_console.bat" ok "Done."
echo.
echo     Phone address:  %PHONE_URL%
echo.
call "%ROOT%tools\deploy_console.bat" info "Enter this address in the phone app. It is also saved in logs\phone-url.txt."
"%PY%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%PORT%/', timeout=2)" >nul 2>&1
if errorlevel 1 call "%ROOT%tools\deploy_console.bat" warn "The system is not running right now. Run START_SYSTEM.bat or INSTALL_AUTOSTART.bat."
endlocal
pause
exit /b 0

:not_ready
call "%ROOT%tools\deploy_console.bat" error "Production runtime is not ready. Run SETUP_OFFLINE.bat first."
goto fail
:no_tailscale
call "%ROOT%tools\deploy_console.bat" error "Tailscale is not installed. Install it from https://tailscale.com/download/windows, log in, then run this file again."
goto fail
:not_logged_in
call "%ROOT%tools\deploy_console.bat" error "Tailscale is still not logged in. Log in from the Tailscale tray icon, then run this file again."
goto fail
:serve_failed
call "%ROOT%tools\deploy_console.bat" error "Could not publish the system. See the message above and logs\setup-phone-access.log."
goto fail
:fail
endlocal
pause
exit /b 1
