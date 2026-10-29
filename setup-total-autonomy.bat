@echo off
chcp 65001 >nul
title LUKK-NODE // CONFIGURADOR DE AUTONOMIA TOTAL CERBERUS
color 0C
echo ==============================================================================
echo  🐉 PROYECTO CERBERUS: AUTONOMIA TOTAL DE ARRANQUE EN FRIO (HEADLESS)
echo ==============================================================================
echo.

:: 1. Comprobar privilegios de Administrador
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Solicitando permisos de Administrador para registrar el servicio de arranque...
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

:: 2. Detectar ruta absoluta real del ejecutable de Python
echo [*] Detectando interprete de Python en el sistema...
set PYTHON_EXE=
for /f "delims=" %%I in ('py -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON_EXE=%%I

if not defined PYTHON_EXE (
    for /f "delims=" %%I in ('where python 2^>nul') do set PYTHON_EXE=%%I
)

if not defined PYTHON_EXE (
    echo [ERROR] No se pudo resolver la ruta de Python automaticamente.
    echo Asegurate de tener Python instalado.
    pause
    exit /b 1
)

echo [OK] Python detectado en: "%PYTHON_EXE%"
echo [OK] Directorio del nodo : "%SCRIPT_DIR%"
echo.

:: 3. Asegurar regla de Firewall para puerto 9876
echo [*] Verificando regla de Windows Defender Firewall (TCP 9876)...
netsh advfirewall firewall add rule name="LukkNode" dir=in action=allow protocol=TCP localport=9876 >nul 2>&1
echo [OK] Firewall configurado.

:: 4. Eliminar tareas previas conflictivas
schtasks /Delete /TN "LukkNodeDaemon" /F >nul 2>&1

:: 5. Generar script lanzador VBS headless con rutas absolutas verificadas
set VBS_TARGET=%SCRIPT_DIR%\start-headless.vbs
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.CurrentDirectory = "%SCRIPT_DIR%"
echo cmdStr = "cmd.exe /c """"%PYTHON_EXE%"""" """"%SCRIPT_DIR%\server.py"""" --auto-gaming"
echo WshShell.Run cmdStr, 0, False
echo Set WshShell = Nothing
) > "%VBS_TARGET%"

echo [OK] Lanzador VBS recompilado con rutas absolutas: "%VBS_TARGET%"

:: 6. Crear Tarea Programada de Sistema (ONSTART, sin esperar login, recuperacion automatica)
echo [*] Registrando Tarea Programada de Arranque en Frio (ONSTART)...
schtasks /Create /TN "LukkNodeDaemon" /TR "wscript.exe \"%VBS_TARGET%\"" /SC ONSTART /RU "SYSTEM" /RL HIGHEST /F

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ==============================================================================
    echo  ✅ AUTONOMIA TOTAL CONSOLIDADA CON EXITO
    echo ==============================================================================
    echo  1. Cada vez que la torre encienda (por boton fisico o Wake-on-LAN^):
    echo     - El servidor lukk-node arrancara a los 5-10 segundos automaticamente.
    echo     - NO requiere que inicies sesion ni introduzcas contrasenas de Windows.
    echo     - Queda 100%% invisible, sin consolas ni ventanas que estorben en pantalla.
    echo  2. Si abres juegos (Minecraft, etc.^), el centinela auto-gaming cuidara tus FPS.
    echo ==============================================================================
    echo.
    echo [*] Iniciando el servicio ahora mismo para verificar...
    schtasks /Run /TN "LukkNodeDaemon"
    echo [OK] Demonio lanzado en segundo plano.
) else (
    echo [ERROR] Fallo la creacion de la tarea programada.
)

echo.
echo Presiona cualquier tecla para finalizar...
pause >nul
