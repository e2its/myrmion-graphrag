from codebase_mcp.parser import get_parser_for_path, module_name_from_path
from codebase_mcp.parser.python_ast import PythonAstParser
from codebase_mcp.parser.treesitter_parser import TreeSitterParser


def _kinds(res):
    return {(n.kind, n.qualified_name) for n in res.nodes}


def _edges(res):
    return {(e.kind, e.src.split(":")[-1], e.dst.split(":")[-1] or e.callee_name) for e in res.edges}


def test_python_nodes_and_edges():
    src = ("from util import helper\n"
           "class Service(Base):\n"
           "    def run(self):\n"
           "        return helper()\n"
           "    def _priv(self):\n"
           "        return self.run()\n")
    res = PythonAstParser().parse_source(src, "svc.py")
    k = _kinds(res)
    assert ("Class", "svc.Service") in k
    assert ("Method", "svc.Service.run") in k
    assert ("Method", "svc.Service._priv") in k
    e = _edges(res)
    assert ("INHERITS", "svc.Service", "Base") in e
    assert ("CALLS", "svc.Service.run", "helper") in e
    # self.run() -> receiver self, callee run
    assert any(x.kind == "CALLS" and x.callee_name == "run" and x.receiver == "self" for x in res.edges)
    assert any(x.kind == "IMPORTS" and x.callee_name == "helper" for x in res.edges)


def test_python_decorator_not_captured_as_call():
    src = ("import functools\n"
           "@functools.lru_cache()\n"
           "def f():\n"
           "    return g()\n")
    res = PythonAstParser().parse_source(src, "m.py")
    calls = {e.callee_name for e in res.edges if e.kind == "CALLS"}
    assert "g" in calls              # llamada real del cuerpo
    assert "lru_cache" not in calls  # el decorador NO es una llamada interna de f


def test_python_syntax_error_graceful():
    res = PythonAstParser().parse_source("def broken(:\n", "bad.py")
    assert len(res.nodes) == 1 and res.nodes[0].kind == "Module"


def test_parse_file(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def f():\n    return 1\n")
    res = PythonAstParser().parse_file(f)
    assert any(n.name == "f" for n in res.nodes)


def test_treesitter_javascript():
    src = "class Widget {\n render(){ draw(); }\n}\nfunction draw(){}\n"
    res = TreeSitterParser("javascript").parse_source(src, "sample.js")
    k = _kinds(res)
    assert ("Class", "sample.Widget") in k
    assert ("Method", "sample.Widget.render") in k
    assert ("Function", "sample.draw") in k
    assert any(e.kind == "CALLS" and e.callee_name == "draw" for e in res.edges)


def test_treesitter_java():
    src = "class Sample extends Base {\n void run(){ helper(); }\n void helper(){}\n}\n"
    res = TreeSitterParser("java").parse_source(src, "Sample.java")
    assert ("Class", "Sample.Sample") in _kinds(res)
    assert any(e.kind == "INHERITS" and e.callee_name == "Base" for e in res.edges)
    assert any(e.kind == "CALLS" and e.callee_name == "helper" for e in res.edges)


def test_registry_by_extension():
    assert isinstance(get_parser_for_path("a.py"), PythonAstParser)
    assert isinstance(get_parser_for_path("a.js"), TreeSitterParser)
    from codebase_mcp.parser.vb_parser import VBParser
    assert isinstance(get_parser_for_path("a.bas"), VBParser)
    assert isinstance(get_parser_for_path("a.vb"), VBParser)
    assert get_parser_for_path("a.unknown") is None


def test_module_name_from_path():
    assert module_name_from_path("pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_name_from_path("mod.py") == "mod"
