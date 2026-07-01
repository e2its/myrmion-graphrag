Imports System.Text

Namespace Banking
    Public Class Ledger
        Inherits BaseLedger
        Implements IAuditable

        Public Sub Post(ByVal amount As Decimal)
            Validate(amount)
            Append(amount)
        End Sub

        Private Function Validate(ByVal amount As Decimal) As Boolean
            Return amount > 0
        End Function
    End Class
End Namespace
