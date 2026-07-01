"""Parser multi-lenguaje con tree-sitter (gramáticas individuales, sin descargas).

Lenguajes: JavaScript, TypeScript/TSX, Java, C#. Usa la API estándar de py-tree-sitter con
los paquetes `tree-sitter-<lang>`. Si la gramática no está instalada, degrada con elegancia
(devuelve solo el nodo Module) para no romper el indexado.

Extrae Class/Function/Method + DEFINES/IMPORTS/INHERITS/CALLS. Las llamadas salen sin
resolver (dst=""); `resolver.py` las afina.
"""

from __future__ import annotations

import pathlib

from ..models import Edge, Node
from .base import ParseResult, module_name_from_path

# Config por lenguaje: módulo de gramática + tipos de nodo relevantes.
LANG_CONFIG = {
    "javascript": {
        "module": "tree_sitter_javascript", "func_name": "language",
        "class": {"class_declaration"},
        "method": {"method_definition"},
        "func": {"function_declaration", "generator_function_declaration"},
        "call": {"call_expression"}, "call_field": "function",
        "import": {"import_statement"},
        "heritage": {"class_heritage", "extends_clause"},
    },
    "typescript": {
        "module": "tree_sitter_typescript", "func_name": "language_typescript",
        "class": {"class_declaration", "abstract_class_declaration", "interface_declaration"},
        "method": {"method_definition", "method_signature"},
        "func": {"function_declaration"},
        "call": {"call_expression"}, "call_field": "function",
        "import": {"import_statement"},
        "heritage": {"class_heritage", "extends_clause"},
    },
    "java": {
        "module": "tree_sitter_java", "func_name": "language",
        "class": {"class_declaration", "interface_declaration", "enum_declaration"},
        "method": {"method_declaration", "constructor_declaration"},
        "func": set(),
        "call": {"method_invocation"}, "call_field": "name",
        "import": {"import_declaration"},
        "heritage": {"superclass", "super_interfaces"},
    },
    "csharp": {
        "module": "tree_sitter_c_sharp", "func_name": "language",
        "class": {"class_declaration", "interface_declaration", "struct_declaration", "enum_declaration"},
        "method": {"method_declaration", "constructor_declaration"},
        "func": set(),
        "call": {"invocation_expression"}, "call_field": "function",
        "import": {"using_directive"},
        "heritage": {"base_list"},
    },
}

_PARSERS: dict = {}


def _get_ts_parser(lang: str):
    if lang in _PARSERS:
        return _PARSERS[lang]
    cfg = LANG_CONFIG[lang]
    import importlib

    from tree_sitter import Language, Parser

    mod = importlib.import_module(cfg["module"])
    language = Language(getattr(mod, cfg["func_name"])())
    parser = Parser(language)
    _PARSERS[lang] = parser
    return parser


class TreeSitterParser:
    def __init__(self, lang: str):
        if lang not in LANG_CONFIG:
            raise ValueError(f"lenguaje tree-sitter no soportado: {lang}")
        self.lang = lang
        self.cfg = LANG_CONFIG[lang]

    def parse_file(self, path) -> ParseResult:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
        return self.parse_source(text, str(path))

    def parse_source(self, source: str, file: str, module: str | None = None) -> ParseResult:
        module = module or module_name_from_path(file)
        raw = source.encode("utf-8", "replace")
        nodes: list = []
        edges: list = []
        mod = Node(kind="Module", qualified_name=module, name=module.split(".")[-1],
                   file=file, lineno=1, end_lineno=max(source.count("\n") + 1, 1), lang=self.lang)
        nodes.append(mod)

        try:
            parser = _get_ts_parser(self.lang)
        except Exception:
            # Gramática no disponible: degradar (solo módulo).
            return ParseResult(nodes, edges)

        tree = parser.parse(raw)
        self._walk(tree.root_node, raw, mod, module, False, None, file, nodes, edges)
        return ParseResult(nodes, edges)

    # --- helpers -----------------------------------------------------------
    def _text(self, node, raw) -> str:
        return raw[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def _name_of(self, node, raw) -> str:
        n = node.child_by_field_name("name")
        if n is not None:
            return self._text(n, raw)
        for c in node.children:
            if c.type.endswith("identifier"):
                return self._text(c, raw)
        return ""

    def _callee_of(self, call_node, raw):
        target = call_node.child_by_field_name(self.cfg["call_field"])
        if target is None:
            return None, ""
        if target.type.endswith("identifier"):
            return self._text(target, raw), ""
        prop = target.child_by_field_name("property") or target.child_by_field_name("name")
        obj = target.child_by_field_name("object") or target.child_by_field_name("expression")
        if prop is not None:
            return self._text(prop, raw), (self._text(obj, raw) if obj is not None else "")
        ident = None
        for c in target.children:
            if c.type.endswith("identifier"):
                ident = c
        return (self._text(ident, raw) if ident is not None else None), ""

    def _heritage(self, class_node, raw, cls_node, edges):
        for c in class_node.children:
            if c.type in self.cfg["heritage"]:
                for d in c.children:
                    if d.type.endswith("identifier") or d.type == "type_identifier":
                        edges.append(Edge(src=cls_node.id, kind="INHERITS",
                                          callee_name=self._text(d, raw)))

    def _walk(self, ts_node, raw, container, container_qn, in_class, current_proc, file, nodes, edges):
        cfg = self.cfg
        for child in ts_node.children:
            t = child.type
            if t in cfg["class"]:
                name = self._name_of(child, raw)
                if not name:
                    self._walk(child, raw, container, container_qn, in_class, current_proc, file, nodes, edges)
                    continue
                qn = f"{container_qn}.{name}"
                cls = Node(kind="Class", qualified_name=qn, name=name, file=file,
                           lineno=child.start_point[0] + 1, end_lineno=child.end_point[0] + 1, lang=self.lang)
                nodes.append(cls)
                edges.append(Edge(src=container.id, kind="DEFINES", dst=cls.id, confidence="exact"))
                self._heritage(child, raw, cls, edges)
                self._walk(child, raw, cls, qn, True, None, file, nodes, edges)
            elif t in cfg["method"] or t in cfg["func"]:
                name = self._name_of(child, raw)
                if not name:
                    self._walk(child, raw, container, container_qn, in_class, current_proc, file, nodes, edges)
                    continue
                kind = "Method" if t in cfg["method"] else "Function"
                qn = f"{container_qn}.{name}"
                proc = Node(kind=kind, qualified_name=qn, name=name, file=file,
                            lineno=child.start_point[0] + 1, end_lineno=child.end_point[0] + 1, lang=self.lang)
                nodes.append(proc)
                edges.append(Edge(src=container.id, kind="DEFINES", dst=proc.id, confidence="exact"))
                self._walk(child, raw, proc, qn, False, proc, file, nodes, edges)
            elif t in cfg["call"]:
                if current_proc is not None:
                    name, receiver = self._callee_of(child, raw)
                    if name:
                        edges.append(Edge(src=current_proc.id, kind="CALLS", callee_name=name,
                                          receiver=receiver, confidence="unresolved"))
                self._walk(child, raw, container, container_qn, in_class, current_proc, file, nodes, edges)
            elif t in cfg["import"]:
                txt = self._text(child, raw)
                edges.append(Edge(src=container.id if container.kind == "Module" else nodes[0].id,
                                  kind="IMPORTS", callee_name=txt.strip()[:60], receiver=txt.strip()))
            else:
                self._walk(child, raw, container, container_qn, in_class, current_proc, file, nodes, edges)
