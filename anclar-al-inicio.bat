@echo off
chcp 65001 >nul
title LUKK-NODE: AUTO-ARRANQUE MINIMIZADO AL INICIAR WINDOWS
color 0C
set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

echo ==============================================================================
echo  🛰️  LUKK-NODE: ANCLANDO WATCHDOG AL INICIO DE WINDOWS
echo ==============================================================================

:: Crear acceso directo en la carpeta de Inicio con WindowStyle=7 (MINIMIZADO)
powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$startup = [Environment]::GetFolderPath('Startup'); " ^
    "$shortcut = Join-Path $startup 'LukkNodeWatchdog.lnk'; " ^
    "$s = $ws.CreateShortcut($shortcut); " ^
    "$s.TargetPath = '%SCRIPT_DIR%\run-watchdog.bat'; " ^
    "$s.WorkingDirectory = '%SCRIPT_DIR%'; " ^
    "$s.WindowStyle = 7; " ^
    "$s.Save(); " ^
    "Write-Host '[OK] Acceso directo permanente creado en Startup:' $shortcut"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ LISTO: A partir de ahora, cada vez que prendas la torre:
    echo    1. Windows levantara LukkNodeWatchdog automaticamente.
    echo    2. Se abrira MINIMIZADO en segundo plano (no tapara tu pantalla).
    echo    3. Cerberus quedara siempre conectado a la laptop desde el primer segundo.
) else (
    echo [ERROR] No se pudo crear el acceso directo.
)

echo ==============================================================================
echo Presiona cualquier tecla para cerrar...
pause >nul
