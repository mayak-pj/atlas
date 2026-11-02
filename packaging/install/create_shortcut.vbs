' Ярлык Atlas на рабочем столе. Права администратора не нужны.
Option Explicit
Dim shell, fso, here, link
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
Set link = shell.CreateShortcut(shell.SpecialFolders("Desktop") & "\Atlas.lnk")
link.TargetPath = here & "\Atlas.bat"
link.WorkingDirectory = here
link.WindowStyle = 7
link.Description = "Atlas"
link.Save
MsgBox "Ярлык Atlas создан на рабочем столе.", vbInformation, "Atlas"
