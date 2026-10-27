@echo off
chcp 65001 >nul
:: ==============================================================================
:: 🛰️ LUKK-NODE: Instalador de Servicio de Arranque en Frío (System Daemon)
:: Registra lukk-node para iniciar al encender el equipo, ANTES del login de Windows
:: ==============================================================================

:: Comprobar permisos de Administrador
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Solicitando permisos de Administrador para registrar el servicio...
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

set SCRIPT_DIR=%~dp0
set SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LukkNode.lnk

echo ==============================================================================
echo  🛰️  LUKK-NODE: Registrando Servicio de Sistema (Boot Startup Daemon)
echo ==============================================================================

:: 1. Limpiar acceso directo de usuario antiguo en Startup
if exist "%SHORTCUT%" (
    del /f /q "%SHORTCUT%" >nul 2>&1
    echo [OK] Removido acceso directo dependiente de login de usuario.
)

:: 2. Eliminar tarea programada anterior si existía
schtasks /Delete /TN "LukkNodeDaemon" /F >nul 2>&1

:: 3. Crear Tarea Programada de Sistema (Disparador: ONSTART, Cuenta: SYSTEM, Privilegio: HIGHEST)
schtasks /Create /TN "LukkNodeDaemon" /TR "wscript.exe \"%SCRIPT_DIR%start-headless.vbs\"" /SC ONSTART /RU "SYSTEM" /RL HIGHEST /F >nul 2>&1

if %ERRORLEVEL% EQU 0 (
    echo [OK] Tarea de Sistema 'LukkNodeDaemon' registrada exitosamente.
    echo      Disparador: En el arranque del equipo (ONSTART, sin esperar login).
    echo      Cuenta: NT AUTHORITY\SYSTEM (Máximo privilegio).
    echo      Directorio: %SCRIPT_DIR%
    echo.
    echo [!] Iniciando demonio lukk-node en segundo plano...
    schtasks /Run /TN "LukkNodeDaemon" >nul 2>&1
    echo ✅ Servicio activo y corriendo de forma permanente.
    echo.
    echo A partir de ahora, la torre arrancará lukk-node automáticamente cada vez
    echo que se encienda por Wake-on-LAN o botón físico, sin necesidad de que nadie
    echo inicie sesión con contraseña.
) else (
    echo [ERROR] No se pudo registrar la tarea en el Programador de Tareas de Windows.
    echo         Verifica que estés ejecutando como Administrador.
)

echo ==============================================================================
pause
