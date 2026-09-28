@echo off
chcp 65001 >nul
echo ======================================
echo    103车间产量看板 Flask服务启动
echo ======================================
set "ROOT=%~dp0"
set "PY_EXE=%ROOT%.venv\Scripts\python.exe"
set "APP_FILE=%ROOT%app.py"

echo 虚拟环境Python路径：%PY_EXE%
echo 后端脚本路径：%APP_FILE%

if not exist "%PY_EXE%" (
    echo 【错误】找不到 .venv\Scripts\python.exe
    pause
    exit /b 1
)
if not exist "%APP_FILE%" (
    echo 【错误】找不到 backend\app.py
    pause
    exit /b 1
)

cd /d "%ROOT%backend"
echo.
echo 👉正在启动Flask，出现 Running on 代表启动成功
echo 👉按 Ctrl+C 停止服务
echo ======================================
echo.

"%PY_EXE%" "%APP_FILE%"
if %errorlevel% neq 0 (
    echo.
    echo ⚠️ Flask程序异常退出，错误码：%errorlevel%
)

echo.
echo Python程序已退出，按任意键关闭窗口
pause >nul