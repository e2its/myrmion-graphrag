"""Modelo de datos del grafo de código: nodos, aristas, snapshots, cambios, anotaciones.

`Node.id` es estable (`kind:qualified_name`, independiente de la línea) para que los diffs
entre commits sean por identidad de símbolo aunque el símbolo se mueva de sitio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Etiquetas de nodo y tipos de arista soportados.
NODE_KINDS = {"File", "Module", "Class", "Function", "Method", "External"}
EDGE_KINDS = {"DEFINES", "IMPORTS", "CALLS", "INHERITS", "IMPLEMENTS"}
CONFIDENCE = {"exact", "heuristic", "unresolved"}


@dataclass(frozen=True)
class Node:
    kind: str            # File|Module|Class|Function|Method|External
    qualified_name: str  # p.ej. "pkg.mod.Clase.metodo"
    name: str            # nombre simple
    file: str = ""       # ruta relativa a la raíz del codebase
    lineno: int = 0
    end_lineno: int = 0
    lang: str = "python"
    body_hash: str = ""  # hash del segmento fuente (para detectar 'modified')

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.qualified_name}"


@dataclass(frozen=True)
class Edge:
    src: str                    # Node.id origen
    kind: str                   # DEFINES|IMPORTS|CALLS|INHERITS|IMPLEMENTS
    dst: str = ""               # Node.id destino resuelto ("" si no resuelto)
    callee_name: str = ""       # nombre crudo del destino (para resolver)
    receiver: str = ""          # receptor de la llamada (self/obj/módulo)
    confidence: str = "exact"   # exact|heuristic|unresolved
    external: bool = False      # el destino es builtin/stdlib/externo

    @property
    def key(self) -> tuple:
        # Identidad para deduplicar: origen + tipo + destino (o nombre si sin resolver).
        return (self.src, self.kind, self.dst or f"?{self.callee_name}:{self.receiver}")


@dataclass(frozen=True)
class Annotation:
    node_id: str
    label: str          # mandatory|reusable|deprecated|keep|<texto>
    note: str = ""


@dataclass(frozen=True)
class Snapshot:
    id: int
    commit_sha: str = ""
    commit_time: str = ""
    branch: str = ""
    created_at: str = ""
    node_count: int = 0
    edge_count: int = 0


@dataclass(frozen=True)
class ChangeRecord:
    snapshot_id: int
    node_id: str
    change: str         # added | removed | modified
    detail: str = ""
