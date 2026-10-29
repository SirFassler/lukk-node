' ==============================================================================
' LUKK-NODE Invisible Launcher (Windows)
' Runs server.py --auto-gaming completely hidden (0 windows, 0 taskbar presence)
' Self-healing: tries py launcher, falls back to python, logs errors if any
' ==============================================================================
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)

WshShell.CurrentDirectory = strDir
' Dual-fallback launcher with error capture:
cmdStr = "cmd.exe /c ""((where py >nul 2>&1 && py server.py --auto-gaming) || python server.py --auto-gaming) 2> ""%TEMP%\lukk_startup_error.log""""
WshShell.Run cmdStr, 0, False

Set WshShell = Nothing
Set fso = Nothing
