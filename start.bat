@echo off
title Tram Data Platform

cd /d "%~dp0"

echo ================================================
echo     Tram Data Export Platform  v1.0
echo ================================================
echo.

REM ============================================
REM  Configuration - edit these for your environment
REM ============================================

if "%ORACLE_USER%"==""     set ORACLE_USER=tram
if "%ORACLE_PASSWORD%"=="" set ORACLE_PASSWORD=tram123
if "%ORACLE_DSN%"==""      set ORACLE_DSN=localhost:1521/ORCL
if "%WEB_PORT%"==""        set WEB_PORT=8080

echo [Config] Oracle User: %ORACLE_USER%
echo [Config] Oracle DSN:  %ORACLE_DSN%
echo [Config] Web Port:    %WEB_PORT%
echo.

REM ============================================
REM  Check Python
REM ============================================
echo [Check] Python environment...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python not found. Please install Python 3.9+
    echo         Download: https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [Check] Python version: %%v

REM ============================================
REM  Create venv
REM ============================================
if not exist "venv\" (
    echo.
    echo [Setup] Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [Error] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

REM ============================================
REM  Install dependencies (always check on startup)
REM ============================================
echo.
echo [Setup] Installing dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [Error] Failed to install dependencies. Check network connection.
    pause
    exit /b 1
)
echo [OK] Dependencies installed

REM ============================================
REM  Init user database
REM ============================================
echo.
echo [Init] User database...
venv\Scripts\python.exe -c "from auth import init_db; init_db()"

REM ============================================
REM  Start server
REM ============================================
echo.
echo ================================================
echo   Starting Web Server
echo   Local:  http://localhost:%WEB_PORT%
echo   LAN:    http://{your-ip}:%WEB_PORT%
echo.
echo   Press Ctrl+C to stop
echo ================================================
echo.

venv\Scripts\python.exe -c "from waitress import serve; from app import create_app; app = create_app(); print('Server is running...'); serve(app, host='0.0.0.0', port=%WEB_PORT%, threads=8)"

echo.
echo Server stopped.
pause