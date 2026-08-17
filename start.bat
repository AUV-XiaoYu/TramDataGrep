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

if "%ORACLE_USER%"=="" set "ORACLE_USER=tram"
if "%ORACLE_PASSWORD%"=="" set "ORACLE_PASSWORD=tram123"
if "%ORACLE_DSN%"=="" set "ORACLE_DSN=localhost:1521/ORCL"
if "%WEB_PORT%"=="" set "WEB_PORT=8080"

:MODE_MENU
if not defined DATA_BACKEND (
    echo.
    echo ================================================
    echo                  选择启动模式
    echo ================================================
    echo [1] 正常模式（连接Oracle） DATA_BACKEND=oracle
    echo [2] 演示模式-大数据（合成数据demo_large） DATA_BACKEND=demo_large
    echo [3] 演示模式-真实数据（SQL文件demo_real） DATA_BACKEND=demo_real

    choice /C 123 /M "请输入选项 [1-3]"
    if errorlevel 3 (
        set "DATA_BACKEND=demo_real"
    ) else if errorlevel 2 (
        set "DATA_BACKEND=demo_large"
    ) else if errorlevel 1 (
        set "DATA_BACKEND=oracle"
    )
) else (
    echo [Info] 已检测到系统环境变量 DATA_BACKEND=%DATA_BACKEND%
)

if "%DATA_BACKEND%"=="demo_real" if not defined REAL_DATA_SQL_PATH (
    echo.
    set /p "REAL_DATA_SQL_PATH=请输入 REAL_DATA_SQL_PATH 路径: "
    if "%REAL_DATA_SQL_PATH%"=="" (
        echo [Error] REAL_DATA_SQL_PATH 不能为空，请重新输入。
        goto MODE_MENU
    )
) else (
    echo [Info] 已检测到系统环境变量 REAL_DATA_SQL_PATH=%REAL_DATA_SQL_PATH%
)

:TABLE_FILTER_MENU
if not defined TABLE_FILTER_MODE (
    echo.
    echo ================================================
    echo                 选择表过滤模式
    echo ================================================
    echo [1] 显示全部表 TABLE_FILTER_MODE=all
    echo [2] 白名单（仅显示指定表） TABLE_FILTER_MODE=whitelist
    echo [3] 黑名单（排除指定表） TABLE_FILTER_MODE=blacklist

    choice /C 123 /M "请输入选项 [1-3]"
    if errorlevel 3 (
        set "TABLE_FILTER_MODE=blacklist"
    ) else if errorlevel 2 (
        set "TABLE_FILTER_MODE=whitelist"
    ) else if errorlevel 1 (
        set "TABLE_FILTER_MODE=all"
    )
) else (
    echo [Info] 已检测到系统环境变量 TABLE_FILTER_MODE=%TABLE_FILTER_MODE%
)

if "%TABLE_FILTER_MODE%"=="whitelist" if not defined TABLE_FILTER_PATTERNS (
    echo.
    set /p "TABLE_FILTER_PATTERNS=请输入 TABLE_FILTER_PATTERNS（逗号分隔表名）: "
    if "%TABLE_FILTER_PATTERNS%"=="" (
        echo [Error] TABLE_FILTER_PATTERNS 不能为空，请重新输入。
        goto TABLE_FILTER_MENU
    )
) else (
    echo [Info] 已检测到系统环境变量 TABLE_FILTER_PATTERNS=%TABLE_FILTER_PATTERNS%
)

if "%TABLE_FILTER_MODE%"=="blacklist" if not defined TABLE_FILTER_PATTERNS (
    echo.
    set /p "TABLE_FILTER_PATTERNS=请输入 TABLE_FILTER_PATTERNS（逗号分隔表名）: "
    if "%TABLE_FILTER_PATTERNS%"=="" (
        echo [Error] TABLE_FILTER_PATTERNS 不能为空，请重新输入。
        goto TABLE_FILTER_MENU
    )
) else (
    echo [Info] 已检测到系统环境变量 TABLE_FILTER_PATTERNS=%TABLE_FILTER_PATTERNS%
)

REM ============================================
REM  Confirm environment to user
REM ============================================
echo.
echo [Confirm] 当前全部环境变量如下：
echo.
set
echo.

echo [Config] Oracle User: %ORACLE_USER%
echo [Config] Oracle DSN:  %ORACLE_DSN%
echo [Config] Web Port:    %WEB_PORT%
echo [Config] DATA_BACKEND: %DATA_BACKEND%
echo [Config] REAL_DATA_SQL_PATH: %REAL_DATA_SQL_PATH%
echo [Config] TABLE_FILTER_MODE: %TABLE_FILTER_MODE%
echo [Config] TABLE_FILTER_PATTERNS: %TABLE_FILTER_PATTERNS%
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
REM TODO: 请在此处填写项目真实启动命令；保留原有启动调用位置，后续替换即可。
REM 例如：
REM venv\Scripts\python.exe -c "from waitress import serve; from app import create_app; serve(create_app(), host='0.0.0.0', port=%WEB_PORT%)"

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