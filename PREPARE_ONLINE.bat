@echo off
chcp 65001 > NUL
title تجهيز نسخة التوزيع - على جهاز فيه إنترنت
cd /d "%~dp0"

REM ============================================================
REM  الملف الوحيد اللي بيستخدم الإنترنت — وبيتشغّل مرة واحدة بس،
REM  على جهاز **تاني** فيه نت، مش على جهاز التشغيل المعزول.
REM
REM  بيجهّز حاجتين جوّه المشروع:
REM     runtime\  : نسخة بايثون محمولة (الجهاز المعزول مش هيحتاج بايثون)
REM     wheels\   : حزم Flask ومعتمداته كملفات جاهزة
REM
REM  وبعدها تنسخ المجلد كله للجهاز المعزول وتشغّل SETUP_OFFLINE.bat
REM ============================================================

set "PYVER=3.11.9"
set "PYZIP=python-%PYVER%-embed-amd64.zip"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/%PYZIP%"

echo ========================================================
echo   تجهيز نسخة التوزيع (بيحتاج إنترنت - مرة واحدة)
echo ========================================================
echo.

REM --- 1) بايثون لازم يكون موجود على الجهاز ده عشان ينزّل الحزم ---
set "SYSPY="
where python >nul 2>&1 && set "SYSPY=python"
if not defined SYSPY where py >nul 2>&1 && set "SYSPY=py"
if not defined SYSPY (
    echo [X] محتاج Python متثبّت على الجهاز ده عشان ينزّل الحزم.
    echo     نزّله من https://www.python.org/  وبعدين شغّل الملف ده تاني.
    pause
    exit /b 1
)

REM --- 2) تنزيل الحزم لمجلد wheels\ ---
echo [*] بينزّل حزم Flask ومعتمداته لويندوز 64-bit / Python 3.11 ...
if not exist "wheels" mkdir wheels
%SYSPY% -m pip download --only-binary=:all: --platform win_amd64 ^
    --python-version 3.11 --implementation cp ^
    --dest wheels flask waitress
if %errorlevel% neq 0 (
    echo [X] فشل تنزيل الحزم. اتأكد من الاتصال بالإنترنت.
    pause
    exit /b 1
)
echo [OK] الحزم اتنزّلت في wheels\
echo.

REM --- 3) تنزيل نسخة بايثون المحمولة (اختياري بس مفضّل جدًا) ---
if exist "runtime\python.exe" (
    echo [OK] runtime\ موجود بالفعل — مش هيتنزّل تاني.
    goto :summary
)

echo [*] بينزّل نسخة بايثون المحمولة %PYVER% ...
curl -L -f -o "%TEMP%\%PYZIP%" "%PYURL%"
if %errorlevel% neq 0 (
    echo.
    echo [!] فشل تنزيل بايثون المحمولة.
    echo     مش مشكلة كبيرة: الجهاز المعزول هيحتاج بس يكون عليه Python 3.11
    echo     وساعتها SETUP_OFFLINE.bat هيعمل venv من wheels\ عادي.
    echo.
    echo     أو نزّلها بإيدك من:
    echo         %PYURL%
    echo     وفكّها في مجلد اسمه:  runtime\
    echo.
    goto :summary
)

if not exist "runtime" mkdir runtime
tar -xf "%TEMP%\%PYZIP%" -C runtime
if %errorlevel% neq 0 (
    echo [!] فشل فكّ الضغط. فكّ %PYZIP% بإيدك في مجلد runtime\
    goto :summary
)
del "%TEMP%\%PYZIP%" >nul 2>&1
echo [OK] بايثون المحمولة جاهزة في runtime\
echo.

:summary
echo ========================================================
echo  خلص التجهيز.
echo.
echo  الخطوات الجاية:
echo    1^) انسخ مجلد المشروع كله للجهاز المعزول
echo    2^) شغّل عليه:  SETUP_OFFLINE.bat   ^(مرة واحدة^)
echo    3^) بعد كده:    START_SYSTEM.bat    ^(كل يوم^)
echo.
echo  الجهاز المعزول مش هيحتاج إنترنت في أي خطوة.
echo ========================================================
echo.
dir /b wheels\*.whl 2>nul | find /c ".whl" > "%TEMP%\c.txt"
set /p NWHL=<"%TEMP%\c.txt"
echo عدد الحزم الجاهزة: %NWHL%
if exist "runtime\python.exe" (echo نسخة بايثون المحمولة: موجودة) else (echo نسخة بايثون المحمولة: مش موجودة - الجهاز هيحتاج Python متثبّت)
echo.
pause
