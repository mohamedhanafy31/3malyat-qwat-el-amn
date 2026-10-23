@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHONUTF8=1"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "setup-offline"

call "%ROOT%tools\deploy_console.bat" step "[1/7] Checking offline package and this PC..."
if not exist "%ROOT%wheels\*.whl" goto no_wheels
call "%ROOT%tools\deploy_console.bat" ok "Offline wheels found."

set "MODE=venv"
set "SYSPY="
set "CHECKPY="
if exist "%ROOT%runtime\python.exe" set "MODE=embedded"
if "!MODE!"=="embedded" set "CHECKPY="%ROOT%runtime\python.exe""
if not "!MODE!"=="embedded" call :find_host_python
if not "!MODE!"=="embedded" if not defined SYSPY goto no_python
if not "!MODE!"=="embedded" set "CHECKPY=!SYSPY!"

set "PRE_OUT=%ROOT%logs\preflight-output.tmp"
!CHECKPY! "%ROOT%tools\deploy_check.py" preflight --mode setup >"!PRE_OUT!" 2>&1
set "PRE_RESULT=!ERRORLEVEL!"
type "!PRE_OUT!"
type "!PRE_OUT!" >>"%DEPLOY_LOG%"
del "!PRE_OUT!" >nul 2>&1
if not "!PRE_RESULT!"=="0" goto preflight_failed

call "%ROOT%tools\deploy_console.bat" step "[2/7] Verifying downloaded assets..."
!CHECKPY! "%ROOT%tools\verify_offline_assets.py" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto assets_failed
call "%ROOT%tools\deploy_console.bat" ok "Runtime, wheels, and OCR files match their checksums."

if "!MODE!"=="embedded" goto embedded
goto system_python

:embedded
call "%ROOT%tools\deploy_console.bat" step "[3/7] Configuring bundled Python (staged, with rollback)..."
"%ROOT%runtime\python.exe" "%ROOT%tools\offline_env.py" install --target "%ROOT%runtime\Lib\site-packages" --quiet >>"%DEPLOY_LOG%" 2>&1
set "INSTALL_RESULT=!ERRORLEVEL!"
if "!INSTALL_RESULT!"=="3" goto data_failed
if not "!INSTALL_RESULT!"=="0" goto failed
set "PY=%ROOT%runtime\python.exe"
call "%ROOT%tools\deploy_console.bat" ok "Bundled Python configured."
goto ocr_step

:system_python
call "%ROOT%tools\deploy_console.bat" step "[3/7] Creating local Python environment..."
set "VENV_CREATED="
if not exist "%ROOT%venv\Scripts\python.exe" (
    !SYSPY! -m venv "%ROOT%venv" >>"%DEPLOY_LOG%" 2>&1
    set "VENV_CREATED=1"
)
set "PY=%ROOT%venv\Scripts\python.exe"
"!PY!" -c "import sys" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto venv_failed
"!PY!" -m pip install --no-index --find-links="%ROOT%wheels" -q flask waitress python-docx openpyxl numpy opencv-python-headless Pillow pytesseract >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto venv_failed
call "%ROOT%tools\deploy_console.bat" ok "Local Python environment configured."

:ocr_step
call "%ROOT%tools\deploy_console.bat" step "[4/7] Checking optional Arabic OCR engine (Tesseract)..."
"!PY!" "%ROOT%tools\ocr_setup.py" status >>"%DEPLOY_LOG%" 2>&1
if not errorlevel 1 goto ocr_ready
set "TESSERACT_INSTALLER="
for %%F in ("%ROOT%tools\offline_installers\tesseract-ocr-w64-setup-*.exe") do set "TESSERACT_INSTALLER=%%~fF"
if not defined TESSERACT_INSTALLER goto ocr_unavailable
call "%ROOT%tools\deploy_console.bat" info "Installing Tesseract for image OCR. Windows may ask for permission once; OCR is optional."
start "" /wait "!TESSERACT_INSTALLER!" /S
>>"%DEPLOY_LOG%" echo Tesseract installer exit code: !ERRORLEVEL!
set /a OCR_WAIT=0
:ocr_wait
"!PY!" "%ROOT%tools\ocr_setup.py" status >>"%DEPLOY_LOG%" 2>&1
if not errorlevel 1 goto ocr_ready
set /a OCR_WAIT+=1
if !OCR_WAIT! GEQ 20 goto ocr_unavailable
timeout /t 1 /nobreak >nul
goto ocr_wait
:ocr_ready
set "OCR_STATE=ready"
call "%ROOT%tools\deploy_console.bat" ok "Optional Arabic OCR is ready."
goto verify
:ocr_unavailable
set "OCR_STATE=unavailable"
call "%ROOT%tools\deploy_console.bat" warn "Image OCR is unavailable: Tesseract or Arabic data is not installed. The personnel system works without it."
call "%ROOT%tools\deploy_console.bat" info "To enable OCR later, install Tesseract with Arabic data (or set TESSERACT_CMD) and run SETUP_OFFLINE.bat again."

:verify
call "%ROOT%tools\deploy_console.bat" step "[5/7] Verifying dependencies, schema, and real data files..."
"!PY!" "%ROOT%tools\offline_env.py" verify --strict --quiet >>"%DEPLOY_LOG%" 2>&1
set "VERIFY_RESULT=!ERRORLEVEL!"
if "!VERIFY_RESULT!"=="3" goto data_failed
if not "!VERIFY_RESULT!"=="0" goto failed
"!PY!" -c "import app; print(app.__file__)" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Dependencies, data schema, every day file, and app import verified."

call "%ROOT%tools\deploy_console.bat" step "[6/7] Checking production entry point..."
"!PY!" -c "import serve; print('serve-import-ok')" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Production entry point verified."

call "%ROOT%tools\deploy_console.bat" step "[7/7] Writing offline deployment manifest..."
"!PY!" "%ROOT%tools\deploy_manifest.py" --mode offline >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 call "%ROOT%tools\deploy_console.bat" warn "Could not write logs\deployment-manifest.txt. Setup itself succeeded."
call "%ROOT%tools\deploy_console.bat" ok "Offline setup completed successfully."
if /i "!OCR_STATE!"=="unavailable" call "%ROOT%tools\deploy_console.bat" warn "Reminder: image OCR is unavailable."
call "%ROOT%tools\deploy_console.bat" info "Run START_SYSTEM.bat to launch the application."
endlocal
exit /b 0

:find_host_python
for %%C in ("py -3" "python" "py") do if not defined SYSPY (
    %%~C "%ROOT%tools\deploy_check.py" host-python --wheel-abi cp311 >>"%DEPLOY_LOG%" 2>&1
    if not errorlevel 1 set "SYSPY=%%~C"
)
exit /b 0

:no_wheels
call "%ROOT%tools\deploy_console.bat" error "No offline wheels found. Run PREPARE_ONLINE.bat first."
goto show_failure
:no_python
call "%ROOT%tools\deploy_console.bat" error "No bundled runtime and no usable 64-bit Python 3.11 was found."
call "%ROOT%tools\deploy_console.bat" info "Run PREPARE_ONLINE.bat first (it downloads the bundled runtime), or install 64-bit Python 3.11 with pip."
goto show_failure
:preflight_failed
call "%ROOT%tools\deploy_console.bat" error "This PC is not ready for setup. Fix the problem listed above and run this file again."
goto show_failure
:assets_failed
call "%ROOT%tools\deploy_console.bat" error "Offline assets are missing, incomplete, or corrupt. Run PREPARE_ONLINE.bat again with internet."
goto show_failure
:venv_failed
call "%ROOT%tools\deploy_console.bat" error "The local Python environment could not be created or filled from the offline wheels."
if defined VENV_CREATED if exist "%ROOT%venv" rmdir /s /q "%ROOT%venv" >nul 2>&1
if defined VENV_CREATED call "%ROOT%tools\deploy_console.bat" info "The incomplete venv folder was removed. Run this file again after fixing the error."
if not defined VENV_CREATED call "%ROOT%tools\deploy_console.bat" info "If the existing venv folder is broken, delete it and run this file again."
goto show_failure
:data_failed
call "%ROOT%tools\deploy_console.bat" error "The application data failed validation. No data was changed and setup stopped."
call "%ROOT%tools\deploy_console.bat" info "Restore a good backup with BACKUPS.bat, or run the migration/update named in the error."
goto show_failure
:failed
call "%ROOT%tools\deploy_console.bat" error "Offline setup failed. See logs\setup-offline.log."
goto show_failure

:show_failure
call "%ROOT%tools\deploy_console.bat" failures
call "%ROOT%tools\deploy_console.bat" info "Details: %DEPLOY_LOG%"
if not defined PERSONNEL_NO_PAUSE if not defined PERSONNEL_SETUP_FROM_START if not defined PERSONNEL_SETUP_FROM_PREPARE (
    echo.
    echo Press any key to close this window after reading the error above.
    pause >nul
)
endlocal
exit /b 1
