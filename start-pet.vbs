' Fairy pet launcher: runs start-pet.ps1 without a console window.
' Place a shortcut to this file in shell:startup to launch the pet with Hana.

Dim shell, fso, here, script
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
script = here & "\start-pet.ps1"

shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & script & """", 0, False
