' ==============================================================================
' LUKK-NODE Invisible Launcher (Windows)
' Runs server.py --auto-gaming completely hidden (0 windows, 0 taskbar presence)
' ==============================================================================
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)

WshShell.CurrentDirectory = strDir
' Uses py launcher first, falls back to python
WshShell.Run "py server.py --auto-gaming", 0, False

Set WshShell = Nothing
Set fso = Nothing
