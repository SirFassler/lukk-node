@echo off
chcp 65001 >nul
echo ==============================================================================
echo  🛑 LUKK-NODE: Deteniendo nodo en segundo plano...
echo ==============================================================================

powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [OK] Nodo de telemetria e inferencia detenido.
echo ==============================================================================
pause
