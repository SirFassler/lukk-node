@echo off
chcp 65001 >nul
echo ==============================================================================
echo  🛰️  LUKK-NODE: Instalador de Inicio Invisible en Segundo Plano
echo ==============================================================================

set SCRIPT_DIR=%~dp0
set VBS_TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LukkNode.vbs

copy /Y "%SCRIPT_DIR%start-headless.vbs" "%VBS_TARGET%" >nul

if %ERRORLEVEL% EQU 0 (
    echo [OK] Servicio configurado exitosamente en la carpeta de Inicio de Windows.
    echo      Ruta: %VBS_TARGET%
    echo.
    echo ✅ A partir de ahora, lukk-node arrancara de forma 100%% invisible al encender
    echo    tu PC, consumiendo solo ~28 MB de RAM y sin ventanas de consola abiertas.
) else (
    echo [ERROR] No se pudo copiar el archivo al inicio de Windows.
)

echo ==============================================================================
pause
