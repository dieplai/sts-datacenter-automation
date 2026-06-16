@echo off
chcp 65001 >nul
REM ============================================================
REM run_supervised.bat -- Windows-native supervisor for acc5
REM
REM Mirrors macOS run_supervised.sh's feature set on Windows:
REM   - Auto-restart on crash (max 30 attempts)
REM   - STOP on clean exit (code 0)
REM   - False-completion detection (re-classify exit 0 as crash if log
REM     contains known failure markers)
REM   - Per-instance Chrome scratch dir + cleanup before each attempt
REM   - Log file with timestamp under logs\
REM   - Email notify on crash / complete / max_restarts (via notify.py)
REM
REM Pre-reqs:
REM   1. setup.bat has been run (venv + requirements installed)
REM   2. Email env vars set if you want alerts (NOTIFY_SMTP_USER,
REM      NOTIFY_SMTP_PASS, NOTIFY_TO_EMAIL)
REM
REM Monitor realtime in another cmd window:
REM   powershell Get-Content "logs\crawl_<TS>.log" -Wait -Tail 50
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set MAX_RESTARTS=30
set RESTART_COOLDOWN=10
set ACCOUNT_NAME=acc5

REM ---- Find Python ----
if defined PYTHON_BIN (
    set "PY=%PYTHON_BIN%"
) else if exist venv\Scripts\python.exe (
    set "PY=venv\Scripts\python.exe"
) else (
    set "PY=python"
)

"!PY!" -c "import selenium" >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo [FATAL] Python at "!PY!" doesn't have selenium installed.
    echo Run setup.bat first to create venv + install requirements.txt
    pause
    exit /b 1
)

REM ---- Per-instance scratch dirs ----
set "INSTANCE_TMPDIR=%CD%\.chrome_tmp"
if not exist "!INSTANCE_TMPDIR!" mkdir "!INSTANCE_TMPDIR!"
if not exist "logs" mkdir "logs"

for %%I in ("%CD%") do set "INSTANCE_NAME=%%~nxI"

set ATTEMPT=0

:loop
set /a ATTEMPT=ATTEMPT+1
if !ATTEMPT! GTR !MAX_RESTARTS! goto give_up

REM ---- Timestamp for log filename (PowerShell, locale-independent) ----
for /f "delims=" %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%a"
set "LOG_FILE=logs\crawl_!TS!.log"

echo.
echo ============================================================
echo [supervisor] attempt !ATTEMPT!/!MAX_RESTARTS!  (instance: !INSTANCE_NAME!)
echo [supervisor] log file: !LOG_FILE!
echo ============================================================

REM ---- Cleanup Chrome before each attempt ----
echo [supervisor] cleaning ghost Chrome processes...
taskkill /f /im chrome.exe /t >nul 2>&1
taskkill /f /im chromedriver.exe /t >nul 2>&1
timeout /t 2 /nobreak >nul

REM ---- Run scraper ----
REM Match run_supervised.sh env vars
set "TMPDIR=!INSTANCE_TMPDIR!"
set "INTERACTIVE_SEARCH=1"
set "FAST_API_MODE=1"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM Python writes its real exit code here (CMD only captures the last pipe
REM segment's code, so without this we'd always see PowerShell's code = 0).
set "EXIT_CODE_FILE=!INSTANCE_TMPDIR!\py_exit_!ATTEMPT!.tmp"
del "!EXIT_CODE_FILE!" 2>nul

REM Tee stdout+stderr to log (UTF-8) while displaying to console.
REM Tee-Object default is UTF-16 LE on PS 5.1 — use ForEach-Object+Out-File for UTF-8.
"!PY!" -u run.py 2>&1 | powershell -NoProfile -Command "$input | ForEach-Object { Write-Host $_; $_ | Out-File -Append -LiteralPath '!LOG_FILE!' -Encoding utf8 }"

REM Read Python's real exit code from EXIT_CODE_FILE
set "EXIT_CODE=1"
if exist "!EXIT_CODE_FILE!" (
    set /p EXIT_CODE=<"!EXIT_CODE_FILE!"
    del "!EXIT_CODE_FILE!" 2>nul
)

echo [supervisor] python exited with code !EXIT_CODE!

REM ---- False-completion detection ----
REM Check canonical success marker first -- if present, accept clean exit
REM even if earlier log lines had transient errors from self-healed recovery.
findstr /C:"Detail Mode complete!" "!LOG_FILE!" >nul 2>&1
if !ERRORLEVEL! EQU 0 goto on_success

REM Exit 0 but no success marker: scan for false-completion patterns
if "!EXIT_CODE!"=="0" (
    for %%P in (
        "Soft recovery failed"
        "DEEP recovery failed"
        "FATAL: Chrome failed"
        "session not created"
        "Still on login page"
        "Login failed after"
        "Login form never appeared"
        "Core Detail Mode execution failed"
        "CRITICAL DATA VIOLATION"
        "Date Integrity Violation"
        "truly no more data"
    ) do (
        findstr /C:%%P "!LOG_FILE!" >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo [supervisor] WARNING: Exit 0 but found %%P in log -- treating as crash
            set "EXIT_CODE=1"
        )
    )
)

if "!EXIT_CODE!"=="0" goto on_success

:on_crash
REM Auto-fix expected values before restart (reads "Found total records" from log)
if exist scripts\auto_set_expected.py (
    "!PY!" scripts\auto_set_expected.py --log "!LOG_FILE!" >> "!LOG_FILE!" 2>&1
)
echo [supervisor] Crash or error. Sleeping !RESTART_COOLDOWN!s before restart...
timeout /t !RESTART_COOLDOWN! /nobreak >nul
goto loop

:on_success
echo [supervisor] CRAWL COMPLETE (clean exit). See !LOG_FILE!
if exist scripts\notify.py (
    "!PY!" scripts\notify.py --kind complete --reason "clean exit after !ATTEMPT! attempts" --scraper-dir "%CD%" --log "!LOG_FILE!" >> "!LOG_FILE!" 2>&1
)

REM Generate manifest for post-crawl data lineage
set "CRAWL_ATTEMPT=!ATTEMPT!"
if exist scripts\generate_manifest.py (
    "!PY!" scripts\generate_manifest.py --account "!ACCOUNT_NAME!" >> "!LOG_FILE!" 2>&1
)

goto cleanup_and_exit

:give_up
echo [supervisor] Hit MAX_RESTARTS=!MAX_RESTARTS!. Aborting. Latest log: !LOG_FILE!
if exist scripts\notify.py (
    "!PY!" scripts\notify.py --kind max_restarts --reason "Hit MAX_RESTARTS=!MAX_RESTARTS!" --scraper-dir "%CD%" --log "!LOG_FILE!" >> "!LOG_FILE!" 2>&1
)

:cleanup_and_exit
taskkill /f /im chrome.exe /t >nul 2>&1
taskkill /f /im chromedriver.exe /t >nul 2>&1
endlocal
exit /b 0
