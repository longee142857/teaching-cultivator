' Start teaching-cultivator watchdog in its own window (relative to this script).
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
shell.Run "cmd /k """ & root & "\watchdog.bat""", 1, False
