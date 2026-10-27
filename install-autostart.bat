@echo off
chcp 65001 >nul
echo ==============================================================================
echo  🛰️  LUKK-NODE: Instalador de Inicio Invisible en Segundo Plano
echo ==============================================================================

set SCRIPT_DIR=%~dp0
set SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LukkNode.lnk

:: Eliminar archivo vbs viejo si existía
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LukkNode.vbs" (
    del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LukkNode.vbs" >nul 2>&1
)

:: Purgar tarea rota de SYSTEM en schtasks si existía
schtasks /Delete /TN "LukkNodeDaemon" /F >nul 2>&1

:: Crear acceso directo con WorkingDirectory apuntando a la carpeta de lukk-node
powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$s = $ws.CreateShortcut('%SHORTCUT%'); " ^
    "$s.TargetPath = 'wscript.exe'; " ^
    "$s.Arguments = '\"%SCRIPT_DIR%start-headless.vbs\"'; " ^
    "$s.WorkingDirectory = '%SCRIPT_DIR%'; " ^
    "$s.WindowStyle = 7; " ^
    "$s.Save()"

if %ERRORLEVEL% EQU 0 (
    echo [OK] Acceso directo permanente creado en: %SHORTCUT%
    echo      Directorio de trabajo: %SCRIPT_DIR%
    echo.
    echo ✅ A partir de ahora, lukk-node arrancará de forma 100%% automática e invisible
    echo    cada vez que inicies sesión en Windows, con acceso total a tu Python y GPU.
    echo.
    echo [!] Iniciando demonio lukk-node ahora mismo...
    start "" wscript.exe "%SCRIPT_DIR%start-headless.vbs"
    echo [OK] Demonio lanzado en segundo plano.
) else (
    echo [ERROR] No se pudo crear el acceso directo de inicio.
)

echo ==============================================================================
pause
