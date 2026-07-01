from codebase_mcp import queries
from codebase_mcp.graph import InMemoryGraphStore
from codebase_mcp.models import Edge, Node


def _fn(qn, file="m.py"):
    return Node(kind="Function", qualified_name=qn, name=qn.split(".")[-1], file=file)


def _call(a, b):
    return Edge(src=f"Function:{a}", kind="CALLS", dst=f"Function:{b}", callee_name=b.split(".")[-1])


def test_resolve_symbol(py_graph):
    nid, cand = queries.resolve_symbol(py_graph, "helper")
    assert nid == "Function:util.helper" and cand == []
    nid, cand = queries.resolve_symbol(py_graph, "util.helper")
    assert nid == "Function:util.helper"
    nid, cand = queries.resolve_symbol(py_graph, "noexiste")
    assert nid is None and cand == []


def test_resolve_symbol_ambiguous():
    s = InMemoryGraphStore()
    s.upsert_node(_fn("a.dup", file="a.py"))
    s.upsert_node(_fn("b.dup", file="b.py"))
    nid, cand = queries.resolve_symbol(s, "dup")
    assert nid is None and set(cand) == {"a.dup", "b.dup"}


def test_callees_callers_transitive():
    s = InMemoryGraphStore()
    for qn in ("m.a", "m.b", "m.c"):
        s.upsert_node(_fn(qn))
    s.replace_edges([_call("m.a", "m.b"), _call("m.b", "m.c")])
    d1 = queries.callees_transitive(s, "Function:m.a", depth=1)
    assert {x["qualified_name"] for x in d1} == {"m.b"}
    d2 = queries.callees_transitive(s, "Function:m.a", depth=2)
    assert {x["qualified_name"] for x in d2} == {"m.b", "m.c"}
    callers = queries.callers_transitive(s, "Function:m.c", depth=5)
    assert {x["qualified_name"] for x in callers} == {"m.b", "m.a"}


def test_blast_radius_and_cycle():
    s = InMemoryGraphStore()
    for qn in ("m.a", "m.b"):
        s.upsert_node(_fn(qn))
    s.replace_edges([_call("m.a", "m.b"), _call("m.b", "m.a")])  # ciclo
    impact = queries.blast_radius(s, "Function:m.a", depth=5)
    assert {x["qualified_name"] for x in impact} == {"m.b"}  # no cuelga, no duplica


def test_blast_radius_on_fixture(py_graph):
    nid, _ = queries.resolve_symbol(py_graph, "run")
    afectados = {x["qualified_name"] for x in queries.blast_radius(py_graph, nid, depth=5)}
    assert "app.main" in afectados and "svc.Service._priv" in afectados
