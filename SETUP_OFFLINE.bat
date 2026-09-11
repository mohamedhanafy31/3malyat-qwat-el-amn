@echo off
chcp 65001 > NUL
title نظام إدارة القوة - تجهيز الجهاز (مرة واحدة)
cd /d "%~dp0"

REM ============================================================
REM  تجهيز الجهاز — مرة واحدة بس، وبدون إنترنت.
REM  بياخد الحزم الجاهزة من مجلد wheels\ ويفكّها في بيئة التشغيل.
REM  مفيش أي تنزيل هنا: pip بيتنادى بـ--no-index يعني ممنوع عليه
REM  يلمس الشبكة أصلًا، وطريقة الفكّ المباشر مابتستخدمش pip من أساسه.
REM ============================================================

echo ========================================================
echo        تجهيز نظام إدارة القوة على الجهاز
echo             (بدون إنترنت - مرة واحدة)
echo ========================================================
echo.

REM --- 0) لازم تكون الحزم موجودة ---
if not exist "wheels\*.whl" (
    echo [X] مجلد wheels\ فاضي أو مش موجود.
    echo.
    echo     الحزم بتتجهّز مرة واحدة على جهاز فيه إنترنت بالملف:
    echo         PREPARE_ONLINE.bat
    echo     وبعدين تتنقل النسخة كلها للجهاز ده.
    echo.
    pause
    exit /b 1
)

REM ============================================================
REM  الحالة (أ): نسخة بايثون محمولة جوّه المشروع — الأفضل والأضمن
REM ============================================================
if exist "runtime\python.exe" (
    echo [*] لقى نسخة بايثون محمولة في runtime\
    echo [*] بيفكّ الحزم جوّاها...
    echo.
    runtime\python.exe tools\offline_env.py install --target "runtime\Lib\site-packages"
    if %errorlevel% neq 0 goto :failed
    goto :done
)

REM ============================================================
REM  الحالة (ب): بايثون متثبّت على الجهاز — بيتعمل venv محلي
REM ============================================================
set "SYSPY="
where python >nul 2>&1 && set "SYSPY=python"
if not defined SYSPY where py >nul 2>&1 && set "SYSPY=py"

if not defined SYSPY (
    echo [X] مفيش بايثون على الجهاز ولا نسخة محمولة في runtime\
    echo.
    echo     عندك اختيارين:
    echo       1^) جهّز نسخة محمولة على جهاز فيه نت بـ PREPARE_ONLINE.bat
    echo          ^(بيحطّها في runtime\ وساعتها الجهاز ده مش محتاج بايثون خالص^)
    echo       2^) ثبّت Python 3.11 على الجهاز ده من مثبّت محفوظ عندك
    echo.
    pause
    exit /b 1
)

echo [*] بايثون متثبّت على الجهاز — بيجهّز بيئة محلية في venv\
if not exist "venv\Scripts\python.exe" (
    %SYSPY% -m venv venv
    if %errorlevel% neq 0 (
        echo [X] فشل إنشاء البيئة الافتراضية.
        goto :failed
    )
)

echo [*] بيثبّت الحزم من wheels\ ^(--no-index = ممنوع أي اتصال^)...
echo.
venv\Scripts\python.exe -m pip install --no-index --find-links=wheels -q flask
if %errorlevel% neq 0 (
    echo [!] pip مانفعش — بيجرّب الفكّ المباشر بدله...
    venv\Scripts\python.exe tools\offline_env.py install
    if %errorlevel% neq 0 goto :failed
) else (
    venv\Scripts\python.exe -m pip install --no-index --find-links=wheels -q waitress 2>nul
)

:done
echo.
echo ========================================================
echo  التحقق النهائي ^(مع منع أي اتصال بالشبكة^)
echo ========================================================
echo.
if exist "runtime\python.exe" (
    runtime\python.exe tools\offline_env.py verify --strict
) else (
    venv\Scripts\python.exe tools\offline_env.py verify --strict
)
if %errorlevel% neq 0 goto :failed

echo.
echo ========================================================
echo  تم التجهيز بنجاح.
echo.
echo  من دلوقتي شغّل السيستم من:  START_SYSTEM.bat
echo  والنسخ الاحتياطية من     :  BACKUPS.bat
echo.
echo  الجهاز ده مش محتاج إنترنت تاني خالص.
echo ========================================================
echo.
pause
exit /b 0

:failed
echo.
echo [X] التجهيز ما اكتملش. راجع الرسائل فوق.
echo.
pause
exit /b 1
