@echo off
title Finance Tool - Launcher
setlocal

echo ========================================================
echo                 Finance Tool Unified Launcher
echo ========================================================
echo.

:: 1. Check Backend (Port 8000)
echo [1/2] Checking Backend (Port 8000)...
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %ERRORLEVEL% EQU 0 (
    echo       Backend is ALREADY running. Skipping startup.
) else (
    echo       Backend is not running. Starting silently...
    wscript.exe "C:\Users\divit\Desktop\Finance Tool\start_backend_silent.vbs"
    timeout /t 2 /nobreak >nul
    echo       Backend started successfully!
)

echo.

:: 2. Check Frontend (Port 3000)
echo [2/2] Checking Frontend (Port 3000)...
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %ERRORLEVEL% EQU 0 (
    echo       Frontend is ALREADY running on http://localhost:3000.
    echo.
    echo ========================================================
    echo  Both Backend and Frontend are active and running!
    echo ========================================================
    echo.
    echo Press any key to close this window...
    pause >nul
    exit /b
)

echo       Frontend is not running. Starting production frontend...
echo.
echo ========================================================
echo  Finance Tool running at: http://localhost:3000
echo  (Keep this window open to keep the frontend active)
echo ========================================================
echo.

cd /d "C:\Users\divit\Desktop\Finance Tool\frontend"
npm run start

pause
