"""Parser de Python basado en el módulo `ast` de la stdlib (determinista, cero deps).

Extrae Module/Class/Function/Method y aristas DEFINES/IMPORTS/INHERITS/CALLS. Las CALLS
salen sin resolver (dst=""); `resolver.py` las resuelve con la tabla global de símbolos.
"""

from __future__ import annotations

import ast
import hashlib
import pathlib

from ..models import Edge, Node
from .base import ParseResult, module_name_from_path


def _seg_hash(lines, start, end) -> str:
    seg = "\n".join(lines[max(start - 1, 0):max(end, start)])
    return hashlib.md5(seg.encode("utf-8", "replace")).hexdigest()


def _call_target(func):
    if isinstance(func, ast.Name):
        return func.id, ""
    if isinstance(func, ast.Attribute):
        receiver = func.value.id if isinstance(func.value, ast.Name) else ""
        return func.attr, receiver
    return None, ""


def _base_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _iter_calls(node):
    """Itera las llamadas dentro de `node` sin entrar en defs/clases/lambdas anidados.

    Se invoca por cada sentencia del CUERPO de la función, así que NO ve los decoradores
    ni las anotaciones/defaults (que cuelgan del propio FunctionDef, no de su body) y no
    los atribuye como llamadas internas.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
        return
    if isinstance(node, ast.Call):
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _iter_calls(child)


class PythonAstParser:
    lang = "python"
    extensions = (".py",)

    def parse_file(self, path) -> ParseResult:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
        return self.parse_source(text, str(path))

    def parse_source(self, source: str, file: str, module: str | None = None) -> ParseResult:
        module = module or module_name_from_path(file)
        lines = source.splitlines()
        nodes: list = []
        edges: list = []
        mod_node = Node(
            kind="Module", qualified_name=module, name=module.split(".")[-1],
            file=file, lineno=1, end_lineno=max(len(lines), 1), lang="python",
        )
        nodes.append(mod_node)

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ParseResult(nodes, edges)

        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    alias = a.asname or a.name.split(".")[0]
                    edges.append(Edge(src=mod_node.id, kind="IMPORTS",
                                      callee_name=alias, receiver=a.name, confidence="exact"))
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                for a in n.names:
                    alias = a.asname or a.name
                    target = f"{base}.{a.name}" if base else a.name
                    edges.append(Edge(src=mod_node.id, kind="IMPORTS",
                                      callee_name=alias, receiver=target, confidence="exact"))

        self._visit_body(tree.body, mod_node, module, "", file, lines, nodes, edges)
        return ParseResult(nodes, edges)

    def _visit_body(self, body, container, container_qn, class_qn, file, lines, nodes, edges):
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "Method" if class_qn else "Function"
                qn = f"{container_qn}.{stmt.name}"
                end = getattr(stmt, "end_lineno", stmt.lineno)
                fn = Node(kind=kind, qualified_name=qn, name=stmt.name, file=file,
                          lineno=stmt.lineno, end_lineno=end, lang="python",
                          body_hash=_seg_hash(lines, stmt.lineno, end))
                nodes.append(fn)
                edges.append(Edge(src=container.id, kind="DEFINES", dst=fn.id, confidence="exact"))
                for stmt_body in stmt.body:
                    for call in _iter_calls(stmt_body):
                        name, receiver = _call_target(call.func)
                        if name:
                            edges.append(Edge(src=fn.id, kind="CALLS", callee_name=name,
                                              receiver=receiver, confidence="unresolved"))
                self._visit_body(stmt.body, fn, qn, "", file, lines, nodes, edges)
            elif isinstance(stmt, ast.ClassDef):
                qn = f"{container_qn}.{stmt.name}"
                end = getattr(stmt, "end_lineno", stmt.lineno)
                cls = Node(kind="Class", qualified_name=qn, name=stmt.name, file=file,
                           lineno=stmt.lineno, end_lineno=end, lang="python",
                           body_hash=_seg_hash(lines, stmt.lineno, end))
                nodes.append(cls)
                edges.append(Edge(src=container.id, kind="DEFINES", dst=cls.id, confidence="exact"))
                for b in stmt.bases:
                    bn = _base_name(b)
                    if bn:
                        edges.append(Edge(src=cls.id, kind="INHERITS", callee_name=bn,
                                          confidence="unresolved"))
                self._visit_body(stmt.body, cls, qn, qn, file, lines, nodes, edges)
