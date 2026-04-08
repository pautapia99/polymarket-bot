@echo off
REM Mata todos los procesos pythonw.exe (servicios en background).
REM CUIDADO: si tienes otros pythonw corriendo, también morirán.
taskkill /F /IM pythonw.exe 2>nul
echo Servicios detenidos.
timeout /t 2
