"""Interfaz de parser pluggable y registro por extensión.

Cada parser convierte fuente -> (nodos, aristas crudas). Las llamadas (CALLS) y herencias
salen "sin resolver" (dst=""); `resolver.py` las resuelve con la tabla global de símbolos.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field


@dataclass
class ParseResult:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)


def module_name_from_path(path: str) -> str:
    """Deriva un nombre de módulo estable desde la ruta relativa.

    "pkg/sub/mod.py" -> "pkg.sub.mod"; se usa como prefijo de los qualified_name.
    """
    p = pathlib.PurePosixPath(str(path).replace("\\", "/"))
    partes = list(p.parts)
    if partes and partes[-1]:
        partes[-1] = p.stem
    partes = [x for x in partes if x not in ("", ".", "..")]
    return ".".join(partes) if partes else p.stem


# Mapa extensión -> (lang, factory). Se rellena de forma perezosa para no importar
# tree-sitter salvo que haga falta.
_REGISTRY: dict = {}


def _ensure_registry():
    if _REGISTRY:
        return
    from .asp_preprocessor import AspParser
    from .python_ast import PythonAstParser
    from .treesitter_parser import TreeSitterParser
    from .vb_parser import VBParser

    def reg(exts, factory):
        for e in exts:
            _REGISTRY[e] = factory

    reg([".py"], lambda: PythonAstParser())
    reg([".js", ".jsx", ".mjs", ".cjs"], lambda: TreeSitterParser("javascript"))
    reg([".ts", ".tsx"], lambda: TreeSitterParser("typescript"))
    reg([".java"], lambda: TreeSitterParser("java"))
    reg([".cs"], lambda: TreeSitterParser("csharp"))
    reg([".bas", ".cls", ".frm", ".vbs"], lambda: VBParser("vb6"))
    reg([".vb"], lambda: TreeSitterParser("vbnet"))   # VB.NET via tree-sitter (grammar 'vb')
    reg([".asp"], lambda: AspParser())


def supported_extensions() -> set:
    _ensure_registry()
    return set(_REGISTRY)


def get_parser_for_path(path):
    """Devuelve una instancia de parser para la extensión de `path`, o None."""
    _ensure_registry()
    ext = pathlib.Path(str(path)).suffix.lower()
    factory = _REGISTRY.get(ext)
    return factory() if factory else None
