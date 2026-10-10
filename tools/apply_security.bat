@echo off
chcp 65001 >nul
rem ============================================================
rem Workweb security apply script (run as admin)
rem 1. set JWT_SECRET (user + system env)
rem 2. rebuild backup scheduled task as SYSTEM
rem 3. run today backup manually
rem 4. restart Workweb service
rem ============================================================

net session >nul 2>&1
if errorlevel 1 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

set "SEC=1dddafe06feaad5475c2dceb84f29ad5f48fea55bfe53d508fa4045bc2622d79"

echo [1/4] set JWT_SECRET (user + system)
setx JWT_SECRET "%SEC%" >nul
setx JWT_SECRET "%SEC%" /M >nul
echo       done.

echo [2/4] rebuild backup task as SYSTEM, daily 03:00
schtasks /delete /tn "Workweb每日备份" /f >nul 2>&1
schtasks /create /tn "Workweb每日备份" /tr "D:\MyWork\Flask\Workweb\workweb\.venv\Scripts\python.exe D:\MyWork\Flask\Workweb\workweb\backup.py" /sc daily /st 03:00 /ru SYSTEM /f
echo       done.

echo [3/4] run today backup manually
"D:\MyWork\Flask\Workweb\workweb\.venv\Scripts\python.exe" "D:\MyWork\Flask\Workweb\workweb\backup.py"
echo       done.

echo [4/4] restart Workweb service
"D:\MyWork\Flask\Workweb\workweb\tools\nssm\nssm-2.24\win64\nssm.exe" restart Workweb
echo       done.

echo.
echo ============================================================
echo ALL DONE. All users need to login again.
echo ============================================================
pause
