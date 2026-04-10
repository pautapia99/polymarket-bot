@echo off
REM ============================================================
REM Lanza dashboard + collector + tracker en ventanas separadas.
REM Cada servicio en su propia ventana para que veas los logs.
REM Para parar uno, cierra su ventana (X) o pulsa Ctrl+C dentro.
REM ============================================================

set PYEXE=C:\Users\pauta\AppData\Local\Programs\Python\Python312\python.exe
set BASE=%~dp0

start "polybot-dashboard" cmd /k "cd /d %BASE% && %PYEXE% dashboard.py"
start "polybot-collector" cmd /k "cd /d %BASE% && %PYEXE% collector.py"
start "polybot-tracker"   cmd /k "cd /d %BASE% && %PYEXE% trader_tracker.py"

echo.
echo Servicios lanzados en ventanas separadas:
echo   - dashboard  (http://127.0.0.1:5000)
echo   - collector  (50 mercados / 60s)
echo   - tracker    (30 top traders)
echo.
echo Cierra cada ventana cuando quieras pararla.
timeout /t 5
