<!--#include file="Legacy.bas"-->
<html>
<body>
<%
Sub RenderPage()
    Call ShowHeader
    Response.Write "hola"
End Sub

Sub ShowHeader()
    Response.Write "<h1>"
End Sub
%>
</body>
</html>
