@echo off
chcp 65001 > NUL
title نظام إدارة القوة - Personnel System

echo ===================================================
echo           نظام إدارة القوة - التشغيل على ويندوز
echo ===================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [خطأ] Python غير مثبت على الجهاز!
    echo يرجى تثبيت Python 3 من https://www.python.org/ وتحديد "Add Python to PATH" أثناء التثبيت.
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "venv" (
    echo [معلومات] إنشاء بيئة افتراضية (venv)...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo [معلومات] التحقق من التثبيت والاعتماديات...
pip install -q -r requirements.txt waitress pytest

REM Start the server
echo.
echo ===================================================
echo  جاري تشغيل السيرفر على: http://127.0.0.1:5000
echo  اضغط Ctrl+C لإيقاف السيرفر في أي وقت.
echo ===================================================
echo.

python app.py

pause
