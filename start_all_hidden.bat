@echo off
REM ============================================================
REM Lanza los servicios SIN ventanas (background).
REM Logs van a archivos en logs\
REM Para parar:  taskkill /F /IM pythonw.exe
REM (cuidado: mata cualquier pythonw.exe del sistema)
REM ============================================================

set PYWEXE=C:\Users\pautapia\AppData\Local\Programs\Python\Python312\pythonw.exe
set BASE=%~dp0

if not exist "%BASE%logs" mkdir "%BASE%logs"

start "" /B "%PYWEXE%" "%BASE%dashboard.py"        > "%BASE%logs\dashboard.log" 2>&1
start "" /B "%PYWEXE%" "%BASE%collector.py"        > "%BASE%logs\collector.log" 2>&1
start "" /B "%PYWEXE%" "%BASE%trader_tracker.py"   > "%BASE%logs\tracker.log"   2>&1

echo Servicios lanzados en background. Logs en %BASE%logs\
echo Parar todos:  taskkill /F /IM pythonw.exe
timeout /t 3
