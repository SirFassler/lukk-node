@echo off
chcp 65001 >nul

:: Comprobar permisos de Administrador
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Solicitando permisos de Administrador...
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo ==============================================================================
echo  🛰️  LUKK-NODE: Desinstalador de Servicio de Sistema
echo ==============================================================================

schtasks /Delete /TN "LukkNodeDaemon" /F >nul 2>&1
taskkill /F /IM py.exe /FI "WINDOWTITLE eq lukk-node*" >nul 2>&1

echo [OK] Servicio LukkNodeDaemon eliminado del Programador de Tareas.
echo ==============================================================================
pause
