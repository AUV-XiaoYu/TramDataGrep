@echo off
setlocal enabledelayedexpansion

title Tram Data Platform

cd /d "%~dp0"

echo ================================================
echo     Tram Data Export Platform  v1.0
echo ================================================

REM ============================================
REM  默认配置（可用外部环境变量覆盖）
REM ============================================
if "%ORACLE_USER%"=="" set "ORACLE_USER=tram"
if "%ORACLE_PASSWORD%"=="" set "ORACLE_PASSWORD=tram123"
if "%ORACLE_DSN%"=="" set "ORACLE_DSN=localhost:1521/ORCL"
if "%WEB_PORT%"=="" set "WEB_PORT=8080"

REM 默认启动模式 / 表过滤模式（若外部环境变量未设置）
if not defined DATA_BACKEND set "DATA_BACKEND=oracle"
if not defined TABLE_FILTER_MODE set "TABLE_FILTER_MODE=all"

REM ============================================
REM  主菜单（第一级）
REM ============================================
:MAIN_MENU
call :show_status
echo.
echo ================================================
echo                 主 菜 单
echo ================================================
echo   [1] 调整启动模式
echo   [2] 调整黑/白名单/全部显示设置
echo   [3] 启动系统
echo   [4] 退出系统
echo ================================================
choice /C 1234 /N /M "请选择 [1-4]: "
if errorlevel 4 goto EXIT
if errorlevel 3 goto START_SYSTEM
if errorlevel 2 goto FILTER_MENU
if errorlevel 1 goto MODE_MENU

REM ============================================
REM  启动模式菜单（第二级）
REM ============================================
:MODE_MENU
call :show_status
echo.
echo ================================================
echo              调整启动模式
echo ================================================
echo   [1] 正常模式（连接 Oracle）
echo   [2] 演示模式-假数据（无需 Oracle）
echo   [3] 演示模式-真实数据（内置 7.10.csv / 可选 SQL）
echo   [0] 返回主菜单
echo ================================================
choice /C 1230 /N /M "请选择 [1-3]，0 返回: "
if errorlevel 4 goto MAIN_MENU
if errorlevel 3 goto SET_DEMO_REAL
if errorlevel 2 goto SET_DEMO_LARGE
if errorlevel 1 goto SET_ORACLE

:SET_ORACLE
set "DATA_BACKEND=oracle"
echo [OK] 启动模式已设为：正常模式（连接 Oracle）
goto MODE_MENU

:SET_DEMO_LARGE
set "DATA_BACKEND=demo_large"
echo [OK] 启动模式已设为：演示模式-假数据
goto MODE_MENU

:SET_DEMO_REAL
set "DATA_BACKEND=demo_real"
set "REAL_DATA_SQL_PATH="
set /p "REAL_DATA_SQL_PATH=请输入 SQL 文件完整路径（直接回车使用内置 7.10.csv）: "
if not defined REAL_DATA_SQL_PATH (
    echo [OK] 未指定 SQL 文件，将使用内置测试数据 7.10.csv
) else (
    echo [OK] SQL 文件路径已设置：%REAL_DATA_SQL_PATH%
)
echo [OK] 启动模式已设为：演示模式-真实数据
goto MODE_MENU

REM ============================================
REM  黑/白名单菜单（第二级）
REM ============================================
:FILTER_MENU
call :show_status
echo.
echo ================================================
echo          调整黑/白名单/全部显示
echo ================================================
echo   [1] 显示全部表（不过滤）
echo   [2] 白名单（仅显示指定表）
echo   [3] 黑名单（排除指定表）
echo   [0] 返回主菜单
echo ================================================
choice /C 1230 /N /M "请选择 [1-3]，0 返回: "
if errorlevel 4 goto MAIN_MENU
if errorlevel 3 goto SET_BLACKLIST
if errorlevel 2 goto SET_WHITELIST
if errorlevel 1 goto SET_ALL

:SET_ALL
set "TABLE_FILTER_MODE=all"
set "TABLE_FILTER_PATTERNS="
echo [OK] 表过滤已设为：显示全部表
goto FILTER_MENU

:SET_WHITELIST
set "TABLE_FILTER_MODE=whitelist"
echo [OK] 表过滤已设为：白名单
call :INPUT_PATTERNS
goto FILTER_MENU

:SET_BLACKLIST
set "TABLE_FILTER_MODE=blacklist"
echo [OK] 表过滤已设为：黑名单
call :INPUT_PATTERNS
goto FILTER_MENU

REM ============================================
REM  启动系统
REM ============================================
:START_SYSTEM
call :show_status
echo.
echo [即将启动] Oracle User : %ORACLE_USER%
echo [即将启动] Oracle DSN  : %ORACLE_DSN%
echo [即将启动] Web Port    : %WEB_PORT%
echo.
choice /C YN /N /M "确认启动系统？[Y=启动, N=返回]: "
if errorlevel 2 goto MAIN_MENU
if errorlevel 1 goto DO_START

:DO_START
REM ---- 检查 Python ----
echo.
echo [Check] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [Error] 未找到 Python，请安装 Python 3.9+ 并勾选 "Add Python to PATH"
    echo         下载地址: https://www.python.org/downloads/
    pause
    goto MAIN_MENU
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [Check] Python 版本: %%v

REM ---- 创建虚拟环境 ----
if not exist "venv\" (
    echo [Setup] 首次运行，正在创建虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo [Error] 虚拟环境创建失败
        pause
        goto MAIN_MENU
    )
    echo [OK] 虚拟环境创建完成
)

REM ---- 安装依赖 ----
echo [Setup] 检查并安装依赖（首次较慢，请耐心等待）...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [Error] 依赖安装失败，请检查网络连接
    pause
    goto MAIN_MENU
)
echo [OK] 依赖已就绪

REM ---- 初始化用户数据库 ----
echo [Init] 初始化用户数据库...
venv\Scripts\python.exe -c "from auth import init_db; init_db()"

REM ---- 启动服务 ----
echo.
echo ================================================
echo   正在启动 Web 服务
echo   本机访问  : http://localhost:%WEB_PORT%
echo   局域网访问: http://本机IP:%WEB_PORT%
echo   按 Ctrl+C 停止服务
echo ================================================
echo.
venv\Scripts\python.exe -c "from waitress import serve; from app import create_app; app = create_app(); print('Server is running...'); serve(app, host='0.0.0.0', port=%WEB_PORT%, threads=8)"

echo.
echo 服务已停止。
choice /C YN /N /M "是否返回主菜单？[Y=返回, N=退出]: "
if errorlevel 2 goto EXIT
if errorlevel 1 goto MAIN_MENU

REM ============================================
REM  退出
REM ============================================
:EXIT
echo.
echo 感谢使用，再见！
exit /b 0

REM ============================================
REM  子程序：显示状态栏
REM ============================================
:show_status
set "MODE_LABEL=未知"
if "%DATA_BACKEND%"=="oracle" set "MODE_LABEL=正常模式（连接 Oracle）"
if "%DATA_BACKEND%"=="demo_large" set "MODE_LABEL=演示模式-假数据"
if "%DATA_BACKEND%"=="demo_real" set "MODE_LABEL=演示模式-真实数据"

set "FILTER_LABEL=未知"
if "%TABLE_FILTER_MODE%"=="all" set "FILTER_LABEL=显示全部表"
if "%TABLE_FILTER_MODE%"=="whitelist" set "FILTER_LABEL=白名单（仅显示指定表）"
if "%TABLE_FILTER_MODE%"=="blacklist" set "FILTER_LABEL=黑名单（排除指定表）"

echo.
echo ================================================
echo   当前状态
echo     启动模式 : %MODE_LABEL%   [%DATA_BACKEND%]
echo     表过滤   : %FILTER_LABEL%   [%TABLE_FILTER_MODE%]
if not "%TABLE_FILTER_MODE%"=="all" (
    if defined TABLE_FILTER_PATTERNS (
        echo     过滤规则 : %TABLE_FILTER_PATTERNS%
    ) else (
        echo     过滤规则 : （未设置）
    )
)
echo ================================================
exit /b 0

REM ============================================
REM  子程序：输入表名匹配规则（JSON 数组）
REM ============================================
:INPUT_PATTERNS
echo.
echo 请输入过滤规则，格式为 JSON 数组，多个用英文逗号分隔。
echo 其中 %% 表示"匹配任意字符"（即 SQL 通配符）。
echo 例如：["TXN%%","DAILY%%","PASSENGER_FLOW"]
echo 直接回车 = 不设置规则（等同于显示全部）
set "TABLE_FILTER_PATTERNS="
set /p "TABLE_FILTER_PATTERNS=过滤规则: "
if not defined TABLE_FILTER_PATTERNS (
    echo [Info] 未输入规则，表过滤不生效
    exit /b 0
)
echo [OK] 已设置过滤规则：%TABLE_FILTER_PATTERNS%
exit /b 0
