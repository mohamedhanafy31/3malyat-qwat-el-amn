@echo off
rem ASCII-only console helper. Do not add non-ASCII text here.
if /i "%~1"=="init" goto init
if /i "%~1"=="step" goto step
if /i "%~1"=="ok" goto ok
if /i "%~1"=="warn" goto warn
if /i "%~1"=="error" goto error
if /i "%~1"=="info" goto info
if /i "%~1"=="failures" goto failures
exit /b 2

:init
set "DEPLOY_ROOT=%~2"
set "DEPLOY_NAME=%~3"
if not defined DEPLOY_ROOT set "DEPLOY_ROOT=%~dp0..\"
if not exist "%DEPLOY_ROOT%logs" mkdir "%DEPLOY_ROOT%logs" >nul 2>&1
set "DEPLOY_LOG=%DEPLOY_ROOT%logs\%DEPLOY_NAME%.log"
if not defined DEPLOY_NAME set "DEPLOY_LOG=%DEPLOY_ROOT%logs\deployment.log"
rem Each run starts a fresh log so failure lines shown at the end are current.
if exist "%DEPLOY_LOG%" move /y "%DEPLOY_LOG%" "%DEPLOY_LOG%.previous" >nul 2>&1
set "DEPLOY_COLOR="
if defined WT_SESSION set "DEPLOY_COLOR=1"
if defined ANSICON set "DEPLOY_COLOR=1"
if /i "%ConEmuANSI%"=="ON" set "DEPLOY_COLOR=1"
for /f "delims=" %%E in ('echo prompt $E^| cmd') do set "ESC=%%E"
call :write "=================================================" "36"
call :write "Camp Management System Deployment" "36"
call :write "=================================================" "36"
exit /b 0

:step
call :write "%~2" "36"
exit /b 0
:ok
call :write "[OK] %~2" "32"
exit /b 0
:warn
call :write "[WARNING] %~2" "33"
exit /b 0
:error
call :write "[ERROR] %~2" "31"
exit /b 0
:info
call :write "%~2" "36"
exit /b 0
:failures
rem Show the precise failure lines (they start with [X]) recorded by the helper tools.
if exist "%DEPLOY_LOG%" findstr /b /c:"[X]" "%DEPLOY_LOG%"
exit /b 0

:write
set "DEPLOY_MESSAGE=%~1"
setlocal EnableDelayedExpansion
if defined DEPLOY_LOG >>"%DEPLOY_LOG%" echo [%date% %time%] !DEPLOY_MESSAGE!
rem No parenthesized block here: a ")" inside a message would end it early.
if defined DEPLOY_COLOR goto write_color
echo !DEPLOY_MESSAGE!
endlocal
exit /b 0
:write_color
echo !ESC![%~2m!DEPLOY_MESSAGE!!ESC![0m
endlocal
exit /b 0
