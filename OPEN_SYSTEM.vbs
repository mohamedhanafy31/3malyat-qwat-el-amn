Option Explicit

Dim shell, files, root, batchFile, logFile, exitCode, answer
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

root = files.GetParentFolderName(WScript.ScriptFullName)
batchFile = files.BuildPath(root, "START_SYSTEM.bat")
logFile = files.BuildPath(files.BuildPath(root, "logs"), "start-system.log")

If Not files.FileExists(batchFile) Then
    MsgBox "START_SYSTEM.bat is missing from this folder.", vbCritical, "Personnel System"
    WScript.Quit 1
End If

shell.Environment("PROCESS")("PERSONNEL_NO_PAUSE") = "1"
exitCode = shell.Run(Quoted(batchFile), 0, True)

If exitCode <> 0 Then
    answer = MsgBox( _
        "The Personnel System could not start." & vbCrLf & vbCrLf & _
        "Details: " & logFile & vbCrLf & vbCrLf & _
        "Open the log in Notepad now?", _
        vbCritical + vbYesNo, "Personnel System")
    If answer = vbYes And files.FileExists(logFile) Then
        shell.Run "notepad.exe " & Quoted(logFile), 1, False
    End If
End If

WScript.Quit exitCode

Function Quoted(value)
    Quoted = Chr(34) & value & Chr(34)
End Function
