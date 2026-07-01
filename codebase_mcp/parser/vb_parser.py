"""Parser propio de Visual Basic (line-oriented, case-insensitive).

Dialectos:
  - vb6   : VB5/6 y VBScript (.bas=Module, .cls/.frm=Class, Property Get/Let/Set, Implements)
  - vbnet : VB.NET (.vb: Namespace/Class/Module/Structure/Interface/Enum, Imports, Inherits)

No compila VB: extrae inventario/dependencias (nodos + aristas) de forma heurística. Las
llamadas salen con confidence 'heuristic'/'unresolved'; `resolver.py` afina lo que puede.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
from dataclasses import replace

from ..models import Edge, Node
from .base import ParseResult, module_name_from_path

_CLASS_OPEN = re.compile(
    r"^\s*(?:Public\s+|Private\s+|Friend\s+|Partial\s+|NotInheritable\s+|MustInherit\s+)*"
    r"(Class|Module|Structure|Interface|Enum)\s+(\w+)", re.IGNORECASE)
_CLASS_CLOSE = re.compile(r"^\s*End\s+(Class|Module|Structure|Interface|Enum)\b", re.IGNORECASE)
_PROC_OPEN = re.compile(
    r"^\s*(?:Public\s+|Private\s+|Friend\s+|Protected\s+|Shared\s+|Static\s+|Overrides\s+"
    r"|Overridable\s+|MustOverride\s+|Partial\s+)*"
    r"(?:(Sub|Function)\s+(\w+)|Property\s+(?:Get|Let|Set)\s+(\w+))", re.IGNORECASE)
_PROC_CLOSE = re.compile(r"^\s*End\s+(Sub|Function|Property)\b", re.IGNORECASE)
_IMPLEMENTS = re.compile(r"^\s*Implements\s+([\w.]+)", re.IGNORECASE)
_INHERITS = re.compile(r"^\s*Inherits\s+([\w.]+)", re.IGNORECASE)
_IMPORTS = re.compile(r"^\s*Imports\s+([\w.]+)", re.IGNORECASE)
_VB_NAME = re.compile(r'^\s*Attribute\s+VB_Name\s*=\s*"([^"]+)"', re.IGNORECASE)

_CALL_CALL = re.compile(r"\bCall\s+(\w+)\b(?!\.)", re.IGNORECASE)  # no captures el receptor de obj.Metodo
_CALL_MEMBER = re.compile(r"\b(\w+)\.(\w+)\s*\(")
_CALL_BARE = re.compile(r"\b(\w+)\s*\(")

_KEYWORDS = {
    "if", "then", "else", "elseif", "end", "sub", "function", "property", "get", "let",
    "set", "dim", "as", "new", "for", "each", "next", "while", "wend", "do", "loop",
    "select", "case", "with", "call", "return", "and", "or", "not", "is", "class",
    "module", "structure", "interface", "enum", "public", "private", "friend", "byval",
    "byref", "optional", "on", "error", "goto", "resume", "exit", "redim", "to", "step",
    "in", "of", "me", "mybase", "myclass", "true", "false", "nothing", "string", "integer",
    "long", "boolean", "double", "single", "object", "variant", "date", "byte",
}


def _seg_hash(lines, start, end) -> str:
    seg = "\n".join(lines[max(start - 1, 0):max(end, start)])
    return hashlib.md5(seg.encode("utf-8", "replace")).hexdigest()


def _finalize_span(nodes, node, end_lineno, raw_lines):
    """Al cerrar un proc/clase, fija su end_lineno y body_hash reales (para el histórico)."""
    try:
        i = nodes.index(node)
    except ValueError:
        return
    nodes[i] = replace(node, end_lineno=end_lineno,
                       body_hash=_seg_hash(raw_lines, node.lineno, end_lineno))


def _strip_comment(line: str) -> str:
    # Heurística: un apóstrofo fuera de comillas inicia comentario. También REM al inicio.
    if re.match(r"^\s*REM\b", line, re.IGNORECASE):
        return ""
    out, in_str = [], False
    for ch in line:
        if ch == '"':
            in_str = not in_str
        if ch == "'" and not in_str:
            break
        out.append(ch)
    return "".join(out)


def _join_continuations(raw_lines):
    """Une líneas con continuación ` _` y devuelve [(texto, lineno_inicial)]."""
    joined, buf, start = [], "", None
    for i, raw in enumerate(raw_lines, 1):
        line = _strip_comment(raw)
        if start is None:
            start = i
        if re.search(r"\s_\s*$", line):
            buf += re.sub(r"\s_\s*$", " ", line)
        else:
            joined.append((buf + line, start))
            buf, start = "", None
    if buf:
        joined.append((buf, start or 1))
    return joined


class VBParser:
    def __init__(self, dialect: str = "vb6"):
        self.dialect = dialect
        self.lang = "vbnet" if dialect == "vbnet" else "vb6"
        self.extensions = (".vb",) if dialect == "vbnet" else (".bas", ".cls", ".frm", ".vbs")

    def parse_file(self, path) -> ParseResult:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
        return self.parse_source(text, str(path))

    def parse_source(self, source: str, file: str, module: str | None = None) -> ParseResult:
        module = module or module_name_from_path(file)
        raw_lines = source.splitlines()
        logical = _join_continuations(raw_lines)
        nodes: list = []
        edges: list = []

        mod = Node(kind="Module", qualified_name=module, name=module.split(".")[-1],
                   file=file, lineno=1, end_lineno=max(len(raw_lines), 1), lang=self.lang)
        nodes.append(mod)

        # Para .cls/.frm de VB6, el fichero ES una clase implícita.
        ext = pathlib.Path(file).suffix.lower()
        vb_name = None
        for text_line, _ in logical:
            m = _VB_NAME.match(text_line)
            if m:
                vb_name = m.group(1)
                break
        stack = [(mod, module, False)]  # (nodo, qn, es_clase)
        if self.dialect == "vb6" and ext in (".cls", ".frm"):
            cname = vb_name or pathlib.Path(file).stem
            cls = Node(kind="Class", qualified_name=f"{module}.{cname}", name=cname,
                       file=file, lineno=1, end_lineno=max(len(raw_lines), 1), lang=self.lang)
            nodes.append(cls)
            edges.append(Edge(src=mod.id, kind="DEFINES", dst=cls.id, confidence="exact"))
            stack.append((cls, cls.qualified_name, True))

        current_proc = None  # (nodo, qn)

        for text_line, lineno in logical:
            if not text_line.strip():
                continue

            m = _IMPORTS.match(text_line)
            if m:
                edges.append(Edge(src=mod.id, kind="IMPORTS",
                                  callee_name=m.group(1).split(".")[0], receiver=m.group(1)))
                continue
            m = _INHERITS.match(text_line)
            if m and stack[-1][2]:
                edges.append(Edge(src=stack[-1][0].id, kind="INHERITS", callee_name=m.group(1)))
                continue
            m = _IMPLEMENTS.match(text_line)
            if m and stack[-1][2]:
                edges.append(Edge(src=stack[-1][0].id, kind="IMPLEMENTS", callee_name=m.group(1)))
                continue

            m = _CLASS_OPEN.match(text_line)
            if m:
                cname = m.group(2)
                parent_qn = stack[-1][1]
                cls = Node(kind="Class", qualified_name=f"{parent_qn}.{cname}", name=cname,
                           file=file, lineno=lineno, end_lineno=lineno, lang=self.lang)
                nodes.append(cls)
                edges.append(Edge(src=stack[-1][0].id, kind="DEFINES", dst=cls.id, confidence="exact"))
                stack.append((cls, cls.qualified_name, True))
                continue
            if _CLASS_CLOSE.match(text_line):
                if len(stack) > 1:
                    popped = stack.pop()
                    _finalize_span(nodes, popped[0], lineno, raw_lines)
                continue

            m = _PROC_OPEN.match(text_line)
            if m:
                pname = m.group(2) or m.group(3)
                container, container_qn, in_class = stack[-1]
                kind = "Method" if in_class else "Function"
                qn = f"{container_qn}.{pname}"
                if any(n.qualified_name == qn for n in nodes):
                    current_proc = next(n for n in nodes if n.qualified_name == qn)
                    continue
                proc = Node(kind=kind, qualified_name=qn, name=pname, file=file,
                            lineno=lineno, end_lineno=lineno, lang=self.lang)
                nodes.append(proc)
                edges.append(Edge(src=container.id, kind="DEFINES", dst=proc.id, confidence="exact"))
                current_proc = proc
                continue
            if _PROC_CLOSE.match(text_line):
                if current_proc is not None:
                    _finalize_span(nodes, current_proc, lineno, raw_lines)
                current_proc = None
                continue

            if current_proc is not None:
                self._collect_calls(text_line, current_proc, edges)

        return ParseResult(nodes, edges)

    @staticmethod
    def _collect_calls(text_line, proc, edges):
        seen = set()
        member_names = set()
        for m in _CALL_MEMBER.finditer(text_line):
            receiver, name = m.group(1), m.group(2)
            if name.lower() in _KEYWORDS:
                continue
            member_names.add(name)
            key = (name, receiver)
            if key in seen:
                continue
            seen.add(key)
            edges.append(Edge(src=proc.id, kind="CALLS", callee_name=name,
                              receiver=receiver, confidence="unresolved"))
        for m in _CALL_CALL.finditer(text_line):
            name = m.group(1)
            if (name, "") not in seen:
                seen.add((name, ""))
                edges.append(Edge(src=proc.id, kind="CALLS", callee_name=name, confidence="unresolved"))
        for m in _CALL_BARE.finditer(text_line):
            name = m.group(1)
            # salta keywords y nombres ya vistos como miembro (obj.Metodo() cubierto arriba)
            if name.lower() in _KEYWORDS or name in member_names or (name, "") in seen:
                continue
            seen.add((name, ""))
            edges.append(Edge(src=proc.id, kind="CALLS", callee_name=name, confidence="unresolved"))
