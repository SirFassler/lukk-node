@echo off
chcp 65001 >nul
title LUKK-NODE DAEMON WATCHDOG
color 0C
echo ==============================================================================
echo  🛰️  LUKK-NODE: SUPERVISOR RESILIENTE // NODO CERBERUS
echo ==============================================================================

cd /d "%~dp0"

:loop
echo [%date% %time%] 🚀 Iniciando LukkNodeDaemon (server.py)...
(where py >nul 2>&1 && py server.py --auto-gaming) || python server.py --auto-gaming
set EXIT_CODE=%ERRORLEVEL%
echo.
echo [%date% %time%] ⚠️ server.py se cerro (Codigo de salida: %EXIT_CODE%).
echo [%date% %time%] ⏳ Relanzando daemon automaticamente en 2 segundos...
echo ------------------------------------------------------------------------------
timeout /t 2 /nobreak >nul
goto loop
