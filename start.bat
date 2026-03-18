@echo off
setlocal enabledelayedexpansion
title TOS-API Startup

echo ============================================================
echo  TOS-API ^| Starting up...
echo ============================================================
echo.

:: ── 1. Kill stray python and node processes ───────────────────────────────
echo [1/5] Stopping stray python.exe and node.exe...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM node.exe   /T >nul 2>&1
echo       Done.
echo.

:: ── 2. Kill anything holding ports 3000 and 8002 ─────────────────────────
echo [2/5] Freeing ports 3000 and 8002...

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3000 " 2^>nul') do (
    if not "%%a"=="0" (
        echo       Killing PID %%a on port 3000
        taskkill /F /PID %%a >nul 2>&1
    )
)

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8002 " 2^>nul') do (
    if not "%%a"=="0" (
        echo       Killing PID %%a on port 8002
        taskkill /F /PID %%a >nul 2>&1
    )
)
echo       Done.
echo.

:: ── 3. Start Python API server ────────────────────────────────────────────
echo [3/5] Starting Python API on port 8002...
start "TOS-API" cmd /k "cd /d C:\Users\randy\tos-api && venv313\Scripts\activate && uvicorn main:app --reload --port 8002"
echo       Window launched.
echo.

:: ── 4. Wait for API to initialize ────────────────────────────────────────
echo [4/5] Waiting 3s for API to initialize...
timeout /t 3 /nobreak >nul
echo       Ready.
echo.

:: ── 5. Start React dev server ─────────────────────────────────────────────
echo [5/5] Starting React dev server on port 3000...
start "TOS-REACT" cmd /k "cd /d C:\Users\randy\hg-frontend && npm start"
echo       Window launched.
echo.

:: ── 6. Open browser ──────────────────────────────────────────────────────
echo Waiting 5s then opening http://localhost:3000 ...
timeout /t 5 /nobreak >nul
start http://localhost:3000

echo.
echo ============================================================
echo  All services started. Close this window when done.
echo  API:   http://localhost:8002/docs
echo  App:   http://localhost:3000
echo  Settings: http://localhost:8002/settings-ui
echo ============================================================
endlocal
