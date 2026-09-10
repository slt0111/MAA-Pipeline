' MAA 一键挂机 - 静默启动器（备用入口）
' 按顺序找可用的 Python：工具目录下的便携版 → PATH 里的 pythonw / python。
' 每一步都会写入 logs\launcher.log，出问题可直接看这个文件。
Option Explicit

Dim fso, sh, base, logDir, logFile, py, script, candidates, i, c, errDetail
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

base   = fso.GetParentFolderName(WScript.ScriptFullName)
script = base & "\pipeline.py"
logDir = base & "\logs"
logFile = logDir & "\launcher.log"

Sub WriteLog(text)
    On Error Resume Next
    Dim f
    Set f = fso.OpenTextFile(logFile, 8, True)
    f.WriteLine Now & "  " & text
    f.Close
End Sub

On Error Resume Next
If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)
On Error GoTo 0

WriteLog "启动器被调用，脚本目录：" & base

If Not fso.FileExists(script) Then
    WriteLog "失败：找不到 " & script
    MsgBox "找不到 pipeline.py：" & vbCrLf & script, 16, "MAA 一键挂机"
    WScript.Quit 1
End If

candidates = Array( _
    base & "\python\pythonw.exe", _
    base & "\python\python.exe", _
    "pythonw.exe", _
    "python.exe")

py = ""
For i = 0 To UBound(candidates)
    c = candidates(i)
    If InStr(c, "\") > 0 Then
        If fso.FileExists(c) Then py = c
    Else
        py = c
    End If
    If py <> "" Then Exit For
Next

If py = "" Then
    WriteLog "失败：找不到可用的 Python 解释器"
    MsgBox "找不到可用的 Python 解释器。", 16, "MAA 一键挂机"
    WScript.Quit 1
End If

WriteLog "使用解释器：" & py

On Error Resume Next
sh.CurrentDirectory = base
sh.Run """" & py & """ """ & script & """", 0, False
If Err.Number <> 0 Then
    errDetail = "错误 " & Err.Number & "：" & Err.Description
    WriteLog "启动失败：" & errDetail
    MsgBox "启动失败。" & vbCrLf & errDetail & vbCrLf & vbCrLf & _
           "解释器：" & py & vbCrLf & "脚本：" & script, 16, "MAA 一键挂机"
    WScript.Quit 1
End If

WriteLog "已拉起：" & py & " " & script
