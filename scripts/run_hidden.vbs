' Launches daily_update.ps1 with no console window, for the hourly scheduled task.
' The task runs as an interactive logon, so powershell.exe would flash a window every hour;
' wscript is windowless. Run(..., 0, True) = hidden and wait, and its return value is the
' script's exit code, so Task Scheduler's "Last Run Result" stays meaningful.
Dim shell, fso, scriptDir
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WScript.Quit shell.Run("powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & _
    fso.BuildPath(scriptDir, "daily_update.ps1") & """", 0, True)
