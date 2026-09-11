@echo off
chcp 65001 > NUL
title نظام إدارة القوة - التشغيل
cd /d "%~dp0"

REM ============================================================
REM  التشغيل اليومي فقط.
REM  الملف ده **مابيثبّتش أي حاجة** ومابيتصلش بالإنترنت خالص:
REM    - مفيش pip
REM    - مفيش winget
REM    - مفيش تنزيل
REM  تجهيز الجهاز بيتعمل مرة واحدة بس من SETUP_OFFLINE.bat
REM ============================================================

REM --- 1) اختيار مفسّر بايثون: المحمول أولًا، وبعده البيئة الافتراضية ---
set "PY="
if exist "runtime\python.exe"        set "PY=runtime\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

if not defined PY (
    echo.
    echo [X] بيئة التشغيل مش متجهّزة على الجهاز ده.
    echo.
    echo     شغّل الملف ده مرة واحدة بس:  SETUP_OFFLINE.bat
    echo.
    pause
    exit /b 1
)

REM --- 2) التأكد إن الحزم موجودة — من غير أي تثبيت ---
"%PY%" -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [X] حزم التشغيل ناقصة في البيئة.
    echo.
    echo     شغّل:  SETUP_OFFLINE.bat
    echo.
    pause
    exit /b 1
)

REM --- 3) التشغيل ---
if not defined PORT set "PORT=5000"

echo ========================================================
echo   نظام إدارة القوة - إدارة قـوات أمن السويس
echo ========================================================
echo.
echo   الرابط : http://127.0.0.1:%PORT%
echo   للإيقاف: اقفل الشاشة دي أو اضغط Ctrl+C
echo.
echo   (السيستم بيشتغل محليًا بالكامل - مفيش أي اتصال بالإنترنت)
echo ========================================================
echo.

REM فتح المتصفح بعد ثانيتين، من غير أي أدوات خارجية
start "" /b cmd /c "timeout /t 2 >nul & start "" http://127.0.0.1:%PORT%"

REM waitress لو متوفرة (أثبت للتشغيل الطويل)، وإلا سيرفر Flask العادي
"%PY%" -c "import waitress" >nul 2>&1
if %errorlevel%==0 (
    "%PY%" serve.py
) else (
    "%PY%" app.py
)

echo.
echo تم إيقاف السيستم.
pause
