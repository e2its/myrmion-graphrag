from codebase_mcp.parser.asp_preprocessor import AspParser
from codebase_mcp.parser.vb_parser import VBParser


def _names(res, kind):
    return {n.name for n in res.nodes if n.kind == kind}


def _edge_kinds(res):
    return {(e.kind, e.callee_name) for e in res.edges}


def test_vb6_bas():
    src = ("Attribute VB_Name = \"Legacy\"\n"
           "Public Sub Init()\n"
           "    Call Configure\n"
           "End Sub\n"
           "Private Sub Configure()\n"
           "End Sub\n"
           "Public Function Compute(ByVal n As Integer) As Integer\n"
           "End Function\n")
    res = VBParser("vb6").parse_source(src, "Legacy.bas")
    assert _names(res, "Function") == {"Init", "Configure", "Compute"}
    assert ("CALLS", "Configure") in _edge_kinds(res)


def test_vb6_cls_implicit_class_and_implements():
    src = ("Attribute VB_Name = \"Account\"\n"
           "Implements IPayable\n"
           "Public Sub Deposit(ByVal amount As Double)\n"
           "    Call Recalculate\n"
           "End Sub\n"
           "Private Sub Recalculate()\n"
           "End Sub\n")
    res = VBParser("vb6").parse_source(src, "Account.cls")
    assert "Account" in _names(res, "Class")
    assert _names(res, "Method") == {"Deposit", "Recalculate"}
    assert ("IMPLEMENTS", "IPayable") in _edge_kinds(res)


def test_vbnet_namespace_inherits_imports():
    src = ("Imports System.Text\n"
           "Namespace Banking\n"
           "  Public Class Ledger\n"
           "    Inherits BaseLedger\n"
           "    Implements IAuditable\n"
           "    Public Sub Post(ByVal a As Decimal)\n"
           "        Validate(a)\n"
           "    End Sub\n"
           "    Private Function Validate(ByVal a As Decimal) As Boolean\n"
           "    End Function\n"
           "  End Class\n"
           "End Namespace\n")
    res = VBParser("vbnet").parse_source(src, "Modern.vb")
    assert "Ledger" in _names(res, "Class")
    assert _names(res, "Method") == {"Post", "Validate"}
    ek = _edge_kinds(res)
    assert ("INHERITS", "BaseLedger") in ek
    assert ("IMPLEMENTS", "IAuditable") in ek
    assert any(e.kind == "IMPORTS" for e in res.edges)
    assert ("CALLS", "Validate") in ek


def test_vb_continuation_and_comment():
    src = ("Sub A()\n"
           "    Call Foo( _\n"
           "        1)  ' comentario\n"
           "End Sub\n")
    res = VBParser("vb6").parse_source(src, "M.bas")
    assert ("CALLS", "Foo") in _edge_kinds(res)


def test_asp_extracts_vbscript_and_includes():
    src = ('<!--#include file="Legacy.bas"-->\n'
           "<html><%\n"
           "Sub RenderPage()\n"
           "    Call ShowHeader\n"
           "End Sub\n"
           "Sub ShowHeader()\n"
           "End Sub\n"
           "%></html>\n")
    res = AspParser().parse_source(src, "page.asp")
    assert _names(res, "Function") == {"RenderPage", "ShowHeader"}
    assert ("CALLS", "ShowHeader") in _edge_kinds(res)
    assert any(e.kind == "IMPORTS" and "Legacy" in e.callee_name for e in res.edges)
