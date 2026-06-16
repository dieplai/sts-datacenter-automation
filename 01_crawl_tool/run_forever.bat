@echo off
REM ============================================================
REM run_forever.bat -- auto-restart wrapper for Windows
REM
REM Behavior:
REM   - Run python run.py
REM   - If exit code 0 (clean complete) -> stop loop, close browsers, exit
REM   - If exit code 130 (Ctrl+C interrupt) -> stop loop, exit
REM   - Otherwise (crash) -> wait 10s, kill ghost Chrome, restart
REM   - After MAX_RESTARTS consecutive crashes -> give up
REM
REM This matches macOS run_supervised.sh's clean-exit detection so
REM the scraper doesn't infinitely re-run after the data is fully
REM crawled.
REM ============================================================
setlocal enabledelayedexpansion
set MAX_RESTARTS=30
set RESTART_COUNT=0

REM Force UTF-8 so emoji in log() don't crash on Vietnamese Windows (cp1258).
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"

:loop
echo.
echo ==============================================
echo [CLEANUP] Killing ghost browser processes...
taskkill /f /im chrome.exe /t >nul 2>&1
taskkill /f /im chromedriver.exe /t >nul 2>&1

echo ==============================================
echo [START] Attempt !RESTART_COUNT!/!MAX_RESTARTS! -- Running python run.py
echo ==============================================
python run.py
set EXIT_CODE=!ERRORLEVEL!

REM ---- Clean completion ----
if !EXIT_CODE! EQU 0 (
    echo.
    echo ==============================================
    echo [DONE] Crawl complete (exit code 0). Closing browsers...
    taskkill /f /im chrome.exe /t >nul 2>&1
    taskkill /f /im chromedriver.exe /t >nul 2>&1
    echo [DONE] Exiting run_forever.bat -- no auto-restart on success.
    echo ==============================================
    pause
    exit /b 0
)

REM ---- User interrupt (Ctrl+C) ----
if !EXIT_CODE! EQU 130 (
    echo.
    echo ==============================================
    echo [STOPPED] User interrupted (Ctrl+C). Closing browsers...
    taskkill /f /im chrome.exe /t >nul 2>&1
    taskkill /f /im chromedriver.exe /t >nul 2>&1
    echo ==============================================
    pause
    exit /b 130
)

REM ---- Hit max restart cap ----
set /a RESTART_COUNT=!RESTART_COUNT!+1
if !RESTART_COUNT! GEQ !MAX_RESTARTS! (
    echo.
    echo ==============================================
    echo [GIVE UP] Hit MAX_RESTARTS=!MAX_RESTARTS!. Aborting.
    echo Investigate the latest log under logs\ before re-running.
    echo ==============================================
    pause
    exit /b 1
)

REM ---- Crash -> cooldown + restart ----
echo.
echo ==============================================
echo [CRASH] Script exited with code !EXIT_CODE!.
echo [RESTART] Wait 10s before retry !RESTART_COUNT!/!MAX_RESTARTS! (Ctrl+C to abort).
echo ==============================================
timeout /t 10
goto loop
