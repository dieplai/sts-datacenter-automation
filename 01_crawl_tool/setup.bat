@echo off
REM ============================================================
REM Vietnam Customs Data Scraper - Automated Setup Script
REM ============================================================
REM This script automates the setup process for a new machine:
REM 1. Creates Python virtual environment (venv)
REM 2. Activates the virtual environment
REM 3. Upgrades pip to latest version
REM 4. Installs all dependencies from requirements.txt
REM
REM Usage: Simply run this script by double-clicking or from terminal
REM        > setup.bat
REM ============================================================

echo.
echo ============================================================
echo  Vietnam Customs Data Scraper - Setup Script
echo ============================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [1/4] Checking Python version...
python --version

REM Check if venv already exists
if exist "venv\" (
    echo.
    echo [WARNING] Virtual environment 'venv' already exists!
    echo.
    set /p RECREATE="Do you want to recreate it? (y/N): "
    if /i not "%RECREATE%"=="y" (
        echo Skipping venv creation. Using existing environment.
        goto :activate_venv
    )
    echo Removing old virtual environment...
    rmdir /s /q venv
)

echo.
echo [2/4] Creating virtual environment...
python -m venv venv
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment!
    echo Try running: python -m pip install --upgrade pip
    pause
    exit /b 1
)
echo [SUCCESS] Virtual environment created successfully!

:activate_venv
echo.
echo [3/4] Activating virtual environment...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate virtual environment!
    pause
    exit /b 1
)

echo [SUCCESS] Virtual environment activated!
echo.
echo [4/4] Installing dependencies from requirements.txt...
python -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo [WARNING] Failed to upgrade pip, continuing anyway...
)

pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install dependencies!
    echo Please check requirements.txt and your internet connection.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Setup Complete!
echo ============================================================
echo.
echo Virtual environment is ready at: %CD%\venv
echo.
echo Next steps:
echo   1. Configure your credentials in src\config.py
echo   2. Activate the environment: venv\Scripts\activate
echo   3. Run the scraper: python run.py
echo.
echo ============================================================
pause
