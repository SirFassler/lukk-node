@echo off
chcp 65001 >nul
title LUKK-NODE: BLINDAJE DE AUTO-ARRANQUE PERMANENTE
color 0C
echo ==============================================================================
echo  🛰️  LUKK-NODE: REGISTRO PERMANENTE DE INICIO INVISIBLE EN WINDOWS
echo ==============================================================================

set SCRIPT_DIR=%~dp0
set VBS_PATH=%SCRIPT_DIR%start-headless.vbs

:: 1. Verificar existencia de start-headless.vbs
if not exist "%VBS_PATH%" (
    echo [ERROR] No se encontro start-headless.vbs en %SCRIPT_DIR%
    pause
    exit /b 1
)

:: 2. Inyectar clave de ejecucion permanente en HKCU Run (Inmutable y a prueba de reinicios)
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "LukkNodeDaemon" /t REG_SZ /d "wscript.exe \"%VBS_PATH%\"" /f >nul 2>&1

if %ERRORLEVEL% EQU 0 (
    echo [OK] Clave de Registro inyectada exitosamente en HKCU\Run.
    echo      Comando asignado: wscript.exe "%VBS_PATH%"
    echo.
    echo 🛡️  BLINDAJE TOTAL:
    echo    Windows iniciara lukk-node de forma 100%% invisible cada vez que enciendas
    echo    el equipo, sin consolas, sin errores de permisos de SYSTEM y sin depender
    echo    de carpetas temporales.
    echo.
    echo [!] Levantando demonio en segundo plano ahora mismo...
    start "" wscript.exe "%VBS_PATH%"
    echo [OK] Servidor activo en segundo plano.
) else (
    echo [ERROR] No se pudo escribir en el Registro de Windows.
)

echo ==============================================================================
echo Presiona cualquier tecla para cerrar...
pause >nul
