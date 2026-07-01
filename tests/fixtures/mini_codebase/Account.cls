Attribute VB_Name = "Account"
Implements IPayable

Private mBalance As Double

Public Sub Deposit(ByVal amount As Double)
    mBalance = mBalance + amount
    Call Recalculate
End Sub

Private Sub Recalculate()
    mBalance = mBalance
End Sub
