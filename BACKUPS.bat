@echo off
chcp 65001 > NUL
title النسخ الاحتياطية - عرض واستعادة
cd /d "%~dp0"

REM لا إنترنت ولا تثبيت — قراءة واستعادة النسخ المحلية بس.

set "PY="
if exist "runtime\python.exe"        set "PY=runtime\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

if not defined PY (
    echo.
    echo [X] بيئة التشغيل مش متجهّزة. شغّل SETUP_OFFLINE.bat الأول.
    echo.
    pause
    exit /b 1
)

:menu
cls
echo ========================================================
echo            النسخ الاحتياطية لنظام إدارة القوة
echo ========================================================
echo.
echo   [1] عرض كل النسخ وحالتها
echo   [2] فحص سلامة كل النسخ
echo   [3] استعادة أحدث نسخة سليمة
echo   [4] استعادة نسخة باسمها
echo   [5] خروج
echo.
set "choice="
set /p choice="اختار رقم: "

if "%choice%"=="1" goto :do_list
if "%choice%"=="2" goto :do_verify
if "%choice%"=="3" goto :do_latest
if "%choice%"=="4" goto :do_named
if "%choice%"=="5" exit /b 0
goto :menu

:do_list
"%PY%" tools\backup.py list
pause
goto :menu

:do_verify
"%PY%" tools\backup.py verify
pause
goto :menu

:do_latest
echo.
echo [!] اقفل شاشة تشغيل السيستم قبل الاستعادة.
echo.
"%PY%" tools\backup.py restore --latest
pause
goto :menu

REM ملحوظة: الاستعادة بالاسم متعملة كـlabel مش جوّه بلوك if(...)
REM لأن %bname% جوّه بلوك بتتقري وقت تحليل السطر — يعني قبل ما المستخدم
REM يكتب حاجة أصلًا، فبتوصل فاضية دايمًا.
:do_named
echo.
"%PY%" tools\backup.py list
echo.
set "bname="
set /p bname="اكتب اسم النسخة بالكامل: "
if not defined bname goto :menu
echo.
echo [!] اقفل شاشة تشغيل السيستم قبل الاستعادة.
echo.
"%PY%" tools\backup.py restore "%bname%"
pause
goto :menu
