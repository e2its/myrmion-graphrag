Attribute VB_Name = "Legacy"
Public Sub Init()
    Call Configure
    LogMessage "arrancando"
End Sub

Private Sub Configure()
    Dim x As Integer
    x = 1
End Sub

Public Function Compute(ByVal n As Integer) As Integer
    Compute = n * 2
End Function
