@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHONUTF8=1"
set "PROGRAM_FILES_X86=%ProgramFiles(x86)%"
call "%ROOT%tools\deploy_console.bat" init "%ROOT%" "setup-offline"

call "%ROOT%tools\deploy_console.bat" step "[1/6] Checking offline package..."
if not exist "%ROOT%wheels\*.whl" goto no_wheels
call "%ROOT%tools\deploy_console.bat" ok "Offline wheels found."

if exist "%ROOT%runtime\python.exe" goto embedded
goto system_python

:embedded
call "%ROOT%tools\deploy_console.bat" step "[2/6] Configuring bundled Python..."
runtime\python.exe tools\verify_offline_assets.py --quiet >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
runtime\python.exe tools\offline_env.py install --target "runtime\Lib\site-packages" --quiet >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
set "PY=runtime\python.exe"
call "%ROOT%tools\deploy_console.bat" ok "Bundled Python configured."
goto verify

:system_python
call "%ROOT%tools\deploy_console.bat" step "[2/6] Creating local Python environment..."
set "SYSPY="
where python >nul 2>&1 && set "SYSPY=python"
if not defined SYSPY where py >nul 2>&1 && set "SYSPY=py"
if not defined SYSPY goto no_python
%SYSPY% tools\verify_offline_assets.py --quiet >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
if not exist "%ROOT%venv\Scripts\python.exe" %SYSPY% -m venv "%ROOT%venv" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
set "PY=%ROOT%venv\Scripts\python.exe"
"%PY%" -m pip install --no-index --find-links="%ROOT%wheels" -q flask waitress python-docx openpyxl numpy opencv-python-headless Pillow pytesseract >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Local Python environment configured."

:verify
call "%ROOT%tools\deploy_console.bat" step "[3/6] Installing bundled Arabic OCR engine..."
set "TESSERACT_EXE=%ROOT%tools\tesseract\tesseract.exe"
set "TESSDATA_DIR=%ROOT%tools\tesseract\tessdata"
if not exist "!TESSERACT_EXE!" set "TESSERACT_EXE=%ProgramFiles%\Tesseract-OCR\tesseract.exe"
if not exist "!TESSERACT_EXE!" if defined PROGRAM_FILES_X86 set "TESSERACT_EXE=!PROGRAM_FILES_X86!\Tesseract-OCR\tesseract.exe"
if not exist "!TESSERACT_EXE!" set "TESSERACT_EXE=%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"
if not exist "!TESSERACT_EXE!" (
    set "TESSERACT_INSTALLER="
    for %%F in ("%ROOT%tools\offline_installers\tesseract-ocr-w64-setup-*.exe") do set "TESSERACT_INSTALLER=%%~fF"
    if not defined TESSERACT_INSTALLER goto no_tesseract
    start "" /wait "!TESSERACT_INSTALLER!" /S
    set "TESSERACT_INSTALL_RESULT=!ERRORLEVEL!"
    >>"%DEPLOY_LOG%" echo Tesseract installer exit code: !TESSERACT_INSTALL_RESULT!
    set "TESSERACT_EXE=%ROOT%tools\tesseract\tesseract.exe"
    if not exist "!TESSERACT_EXE!" set "TESSERACT_EXE=%ProgramFiles%\Tesseract-OCR\tesseract.exe"
    if not exist "!TESSERACT_EXE!" if defined PROGRAM_FILES_X86 set "TESSERACT_EXE=!PROGRAM_FILES_X86!\Tesseract-OCR\tesseract.exe"
    if not exist "!TESSERACT_EXE!" set "TESSERACT_EXE=%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"
)
set /a TESS_WAIT=0
:wait_tesseract
if exist "!TESSERACT_EXE!" goto tesseract_ready
timeout /t 1 /nobreak >nul
set /a TESS_WAIT+=1
if !TESS_WAIT! LSS 60 goto wait_tesseract
goto no_tesseract
:tesseract_ready
if not exist "!TESSDATA_DIR!" mkdir "!TESSDATA_DIR!" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
copy /Y "%ROOT%tools\offline_installers\ara.traineddata" "!TESSDATA_DIR!\ara.traineddata" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
set "TESSDATA_PREFIX=!TESSDATA_DIR!"
"!TESSERACT_EXE!" --list-langs 2>>"%DEPLOY_LOG%" | findstr /x "ara" >nul
if errorlevel 1 goto no_tesseract
call "%ROOT%tools\deploy_console.bat" ok "Bundled Tesseract and Arabic language data are ready."

call "%ROOT%tools\deploy_console.bat" step "[4/6] Verifying dependencies and import path..."
"%PY%" tools\offline_env.py verify --strict --quiet >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
"%PY%" -c "import app; print(app.__file__)" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Dependencies, schema, database, and app import verified."

call "%ROOT%tools\deploy_console.bat" step "[5/6] Checking production entry point..."
"%PY%" -c "import serve; print('serve-import-ok')" >>"%DEPLOY_LOG%" 2>&1
if errorlevel 1 goto failed
call "%ROOT%tools\deploy_console.bat" ok "Production entry point verified."

call "%ROOT%tools\deploy_console.bat" step "[6/6] Writing offline deployment manifest..."
>"%ROOT%logs\deployment-manifest.txt" echo setup=%date% %time%
>>"%ROOT%logs\deployment-manifest.txt" echo mode=offline
>>"%ROOT%logs\deployment-manifest.txt" echo python=%PY%
call "%ROOT%tools\deploy_console.bat" ok "Offline setup completed successfully."
call "%ROOT%tools\deploy_console.bat" info "Run START_SYSTEM.bat to launch the application."
endlocal
exit /b 0

:no_wheels
call "%ROOT%tools\deploy_console.bat" error "No offline wheels found. Run PREPARE_ONLINE.bat first."
goto show_failure
:no_python
call "%ROOT%tools\deploy_console.bat" error "No bundled runtime and no system Python was found."
goto show_failure
:no_tesseract
call "%ROOT%tools\deploy_console.bat" error "Bundled Tesseract OCR or Arabic language data is missing."
goto show_failure
:failed
call "%ROOT%tools\deploy_console.bat" error "Offline setup failed. See logs\setup-offline.log."
goto show_failure

:show_failure
call "%ROOT%tools\deploy_console.bat" info "Details: %DEPLOY_LOG%"
if not defined PERSONNEL_NO_PAUSE if not defined PERSONNEL_SETUP_FROM_START if not defined PERSONNEL_SETUP_FROM_PREPARE (
    echo.
    echo Press any key to close this window after reading the error above.
    pause >nul
)
endlocal
exit /b 1
