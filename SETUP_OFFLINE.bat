@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "setup-offline"

call "%ROOT%tools\deploy_console.bat" step "[1/5] Checking offline package..."
if not exist "%ROOT%wheels\*.whl" goto no_wheels
call "%ROOT%tools\deploy_console.bat" ok "Offline wheels found."

if exist "%ROOT%runtime\python.exe" goto embedded
goto system_python

:embedded
call "%ROOT%tools\deploy_console.bat" step "[2/5] Configuring bundled Python..."
runtime\python.exe tools\offline_env.py install --target "runtime\Lib\site-packages" --quiet >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
set "PY=runtime\python.exe"
call "%ROOT%tools\deploy_console.bat" ok "Bundled Python configured."
goto verify

:system_python
call "%ROOT%tools\deploy_console.bat" step "[2/5] Creating local Python environment..."
set "SYSPY="
where python >nul 2>&1 && set "SYSPY=python"
if not defined SYSPY where py >nul 2>&1 && set "SYSPY=py"
if not defined SYSPY goto no_python
if not exist "%ROOT%venv\Scripts\python.exe" %SYSPY% -m venv "%ROOT%venv" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
set "PY=%ROOT%venv\Scripts\python.exe"
"%PY%" -m pip install --no-index --find-links="%ROOT%wheels" -q flask waitress python-docx >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Local Python environment configured."

:verify
call "%ROOT%tools\deploy_console.bat" step "[3/5] Verifying dependencies and import path..."
"%PY%" tools\offline_env.py verify --strict --quiet >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
"%PY%" -c "import app; print(app.__file__)" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Dependencies, schema, database, and app import verified."

call "%ROOT%tools\deploy_console.bat" step "[4/5] Checking production entry point..."
"%PY%" -c "import serve; print('serve-import-ok')" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Production entry point verified."

call "%ROOT%tools\deploy_console.bat" step "[5/5] Writing offline deployment manifest..."
>"%ROOT%logs\deployment-manifest.txt" echo setup=%date% %time%
>>"%ROOT%logs\deployment-manifest.txt" echo mode=offline
>>"%ROOT%logs\deployment-manifest.txt" echo python=%PY%
call "%ROOT%tools\deploy_console.bat" ok "Offline setup completed successfully."
call "%ROOT%tools\deploy_console.bat" info "Run START_SYSTEM.bat to launch the application."
endlocal
exit /b 0

:no_wheels
call "%ROOT%tools\deploy_console.bat" error "No offline wheels found. Run PREPARE_ONLINE.bat first."
endlocal
exit /b 1
:no_python
call "%ROOT%tools\deploy_console.bat" error "No bundled runtime and no system Python was found."
endlocal
exit /b 1
:failed
call "%ROOT%tools\deploy_console.bat" error "Offline setup failed. See logs\setup-offline.log."
endlocal
exit /b 1
