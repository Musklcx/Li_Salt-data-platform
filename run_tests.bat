@echo off
REM 接口自动化冒烟测试（只读，不污染数据库）
cd /d "%~dp0"
echo ==========================================
echo  接口自动化测试 - 正在运行...
echo ==========================================
".venv\Scripts\python.exe" -m unittest tests.test_api -v
echo.
echo ==========================================
if %errorlevel%==0 (
    echo 全部测试通过！
) else (
    echo 存在失败项，请查看上方结果。
)
echo ==========================================
pause
