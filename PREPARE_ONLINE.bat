@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "prepare-online"

call "%ROOT%tools\deploy_console.bat" step "[1/6] Checking host Python..."
set "SYSPY="
where python >nul 2>&1 && set "SYSPY=python"
if not defined SYSPY where py >nul 2>&1 && set "SYSPY=py"
if not defined SYSPY goto no_python
call "%ROOT%tools\deploy_console.bat" ok "Host Python found."

call "%ROOT%tools\deploy_console.bat" step "[2/6] Downloading offline wheels..."
if not exist "%ROOT%wheels" mkdir "%ROOT%wheels"
%SYSPY% -m pip download --only-binary=:all: --platform win_amd64 --python-version 3.11 --implementation cp --dest "%ROOT%wheels" flask waitress python-docx >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Offline wheels ready."

call "%ROOT%tools\deploy_console.bat" step "[3/6] Preparing embedded Python..."
set "PYVER=3.11.9"
set "PYZIP=python-%PYVER%-embed-amd64.zip"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/%PYZIP%"
if not exist "%ROOT%runtime\python.exe" (
    curl -L -f -o "%TEMP%\%PYZIP%" "%PYURL%" >>"%DEPLOY_LOG%" 2>&1
    if errorlevel 1 goto failed
    if not exist "%ROOT%runtime" mkdir "%ROOT%runtime"
    tar -xf "%TEMP%\%PYZIP%" -C "%ROOT%runtime" >>"%DEPLOY_LOG%" 2>&1
    if errorlevel 1 goto failed
    del "%TEMP%\%PYZIP%" >nul 2>&1
)
if not exist "%ROOT%runtime\python.exe" goto failed
call "%ROOT%tools\deploy_console.bat" ok "Embedded Python ready."

call "%ROOT%tools\deploy_console.bat" step "[4/6] Installing offline dependencies and configuring paths..."
runtime\python.exe tools\offline_env.py install --target "runtime\Lib\site-packages" --quiet >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Dependencies and embedded import path ready."

call "%ROOT%tools\deploy_console.bat" step "[5/6] Verifying relocatable app import..."
runtime\python.exe -c "import app; print(app.__file__)" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Application import verified."

call "%ROOT%tools\deploy_console.bat" step "[6/6] Writing deployment manifest..."
>"%ROOT%logs\deployment-manifest.txt" echo prepared=%date% %time%
>>"%ROOT%logs\deployment-manifest.txt" echo python=3.11 embedded
>>"%ROOT%logs\deployment-manifest.txt" echo wheels=flask waitress python-docx
call "%ROOT%tools\deploy_console.bat" ok "Deployment package is ready for USB transfer."
call "%ROOT%tools\deploy_console.bat" info "Copy the complete project folder to the offline PC."
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
