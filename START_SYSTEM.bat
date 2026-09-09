@echo off
chcp 65001 > NUL
title نظام إدارة القوة - التشغيل الفوري

echo ========================================================
echo         🚀 جاري إعداد وتشغيل نظام إدارة القوة...
echo ========================================================
echo.

REM 1. Check Python installation
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [!] بايثون غير مثبت على الجهاز.
        echo [!] جاري محاولة التثبيت التلقائي من خلال Windows Package Manager (winget)...
        echo.
        winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
        if %errorlevel% neq 0 (
            echo.
            echo [X] لم نتمكن من التثبيت التلقائي. 
            echo يرجى تنزيل Python 3 وتثبيته من: https://www.python.org/
            echo ⚠️ تنبيه هام: تأكد من تحديد خيار "Add Python to PATH" أثناء التثبيت!
            pause
            exit /b 1
        )
        echo [OK] تم تثبيت Python بنجاح! يرجى إعادة تشغيل السكربت.
        pause
        exit /b 0
    )
)

REM 2. Create Virtual Environment if missing
if not exist "venv" (
    echo [*] جاري إعداد البيئة الافتراضية للسيستم لأول مرة (venv)...
    python -m venv venv
    if %errorlevel% neq 0 (
        py -m venv venv
    )
)

REM 3. Activate Virtual Environment
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [X] تعذر تفعيل البيئة الافتراضية.
    pause
    exit /b 1
)

REM 4. Install & Update Dependencies
echo [*] جاري فحص وتثبيت جميع المكتبات المطلوبة للسيستم...
python -m pip install --upgrade pip -q
pip install -q -r requirements.txt waitress pytest

REM 5. Auto open browser
echo.
echo ========================================================
echo  ✅ تم إعداد وتحديث كل شيء بنجاح!
echo  🌐 جاري تشغيل السيرفر وفتح المتصفح تلقائياً...
echo  رابط السيستم: http://127.0.0.1:5000
echo  (لإيقاف السيستم في أي وقت: اغلق هذه الشاشة أو اضغط Ctrl+C)
echo ========================================================
echo.

REM Launch browser in 2 seconds asynchronously
start "" powershell -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:5000'" >nul 2>&1

REM 6. Run Application
python app.py

pause
