@echo off
chcp 65001 >nul
title Cloudflare IP Auto-Updater (Windows Task Scheduler)

echo ================================================
echo   Cloudflare IP Auto-Updater
echo   Windows Task Scheduler Version
echo ================================================

cd /d "%~dp0"

echo [%date% %time%] Starting workflow trigger...
python trigger_workflow.py

if %errorlevel% equ 0 (
    echo [%date% %time%] ✅ Success!
) else (
    echo [%date% %time%] ❌ Failed!
)

echo.
echo ================================================
echo Next run: 1 hour later (or as configured)
echo ================================================
timeout /t 5
