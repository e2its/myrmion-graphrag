"""Preprocesador de ASP clásico (.asp): extrae el VBScript embebido y las inclusiones.

- Bloques `<% ... %>` (y `<%= expr %>`) → se concatenan y se pasan al parser de VB6/VBScript.
- Directivas `<!--#include file="..."-->` / `virtual="..."` → aristas IMPORTS del módulo.
El markup HTML/`.aspx` en sí queda fuera de esta primera fase.
"""

from __future__ import annotations

import pathlib
import re

from ..models import Edge
from .base import ParseResult, module_name_from_path
from .vb_parser import VBParser

_BLOCK = re.compile(r"<%(.*?)%>", re.DOTALL)
_INCLUDE = re.compile(
    r'<!--\s*#include\s+(?:file|virtual)\s*=\s*"([^"]+)"\s*-->', re.IGNORECASE)


class AspParser:
    lang = "asp"
    extensions = (".asp",)

    def parse_file(self, path) -> ParseResult:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
        return self.parse_source(text, str(path))

    def parse_source(self, source: str, file: str, module: str | None = None) -> ParseResult:
        module = module or module_name_from_path(file)
        scripts = []
        for m in _BLOCK.finditer(source):
            code = re.sub(r"^\s*=", "", m.group(1))  # <%= expr %> -> expr
            scripts.append(code)
        vbsrc = "\n".join(scripts)
        result = VBParser("vb6").parse_source(vbsrc, file, module)

        mod_id = f"Module:{module}"
        for m in _INCLUDE.finditer(source):
            inc = m.group(1)
            result.edges.append(Edge(src=mod_id, kind="IMPORTS",
                                     callee_name=pathlib.Path(inc).name, receiver=inc))
        return result
