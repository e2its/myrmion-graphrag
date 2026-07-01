#!/usr/bin/env python3
"""
Consistencia del backend HÍBRIDO de LightRAG (grafo en Neo4j + vectores/KV/estado en
PostgreSQL).

Son dos bases de datos sin transacción distribuida: no hay 2PC entre Neo4j y Postgres y
LightRAG no lo implementa. Este módulo es un **supervisor por encima de LightRAG** (no se
toca su interior) que garantiza consistencia FUERTE AUTO-REPARABLE — nunca *se quedan*
desalineadas: se detecta y se repara toda deriva. No es un candado transaccional instantáneo.

Tres mecanismos, todos con la lógica pura aislada y testeable sin BD reales:
  1. Health-gate: no escribir salvo que Neo4j Y Postgres Y LightRAG respondan.
  2. Saga con reintentos automáticos + compensación (pasos idempotentes).
  3. Reconciliación: diff de conjuntos (grafo vs vector vs docs procesados) + plan de reparación.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol


# --- 1. Health-gate --------------------------------------------------------
def health_gate(checks: dict) -> tuple:
    """Evalúa checks {nombre: callable()->bool}. Devuelve (todos_ok, [nombres_que_fallan]).

    Un check que lanza excepción cuenta como fallo. El gate se usa ANTES de cualquier
    escritura: si algún backend falta, se aborta en vez de escribir en uno solo.
    """
    faltan = []
    for name, check in checks.items():
        try:
            ok = check()
        except Exception:
            ok = False
        if not ok:
            faltan.append(name)
    return (len(faltan) == 0, faltan)


# --- 2. Saga con reintentos + compensación ---------------------------------
@dataclass
class SagaStep:
    name: str
    action: Callable[[], object]
    compensate: Callable[[], object] | None = None


class SagaError(Exception):
    def __init__(self, step: str, attempts: int, cause: BaseException):
        self.step = step
        self.attempts = attempts
        self.cause = cause
        super().__init__(f"saga fallo en '{step}' tras {attempts} intentos: {cause!r}")


def _compensate(done: list) -> None:
    # Deshace en orden inverso; best-effort (lo que no se pueda deshacer lo captará la
    # reconciliación posterior).
    for step in reversed(done):
        if step.compensate:
            try:
                step.compensate()
            except Exception:
                pass


def run_saga(steps: Iterable, max_retries: int = 3, sleep: Callable[[int], object] | None = None) -> list:
    """Ejecuta pasos idempotentes con reintentos. Si un paso agota `max_retries`, compensa
    los pasos ya completados (orden inverso) y lanza `SagaError`.

    Devuelve la lista de nombres de pasos completados. `sleep(intento)` es inyectable para
    el backoff (por defecto no espera; en tests se pasa un no-op).
    """
    sleep = sleep or (lambda attempt: None)
    done: list = []
    for step in steps:
        last: BaseException | None = None
        for attempt in range(1, max_retries + 1):
            try:
                step.action()
                done.append(step)
                break
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < max_retries:
                    sleep(attempt)
        else:
            _compensate(done)
            raise SagaError(step.name, max_retries, last)
    return [s.name for s in done]


# --- 3. Reconciliación -----------------------------------------------------
@dataclass
class Drift:
    missing_in_graph: set = field(default_factory=set)   # docs procesados sin entidades en Neo4j
    missing_in_vector: set = field(default_factory=set)  # docs procesados sin vectores en Postgres
    orphan_in_graph: set = field(default_factory=set)    # ids en Neo4j que no son docs procesados
    orphan_in_vector: set = field(default_factory=set)   # ids en Postgres que no son docs procesados

    def is_aligned(self) -> bool:
        return not (
            self.missing_in_graph
            or self.missing_in_vector
            or self.orphan_in_graph
            or self.orphan_in_vector
        )

    def summary(self) -> str:
        if self.is_aligned():
            return "Neo4j y Postgres ALINEADOS."
        return (
            "DERIVA detectada: "
            f"falta_en_grafo={len(self.missing_in_graph)} "
            f"falta_en_vector={len(self.missing_in_vector)} "
            f"huerfano_grafo={len(self.orphan_in_graph)} "
            f"huerfano_vector={len(self.orphan_in_vector)}"
        )


def alignment_diff(expected: Iterable, in_graph: Iterable, in_vector: Iterable) -> Drift:
    """Compara los docs procesados (fuente de verdad) con lo presente en grafo y vectores."""
    expected, in_graph, in_vector = set(expected), set(in_graph), set(in_vector)
    return Drift(
        missing_in_graph=expected - in_graph,
        missing_in_vector=expected - in_vector,
        orphan_in_graph=in_graph - expected,
        orphan_in_vector=in_vector - expected,
    )


@dataclass(frozen=True)
class RepairAction:
    kind: str   # reindex | delete_orphan_graph | delete_orphan_vector
    doc_id: str


def repair_plan(drift: Drift) -> list:
    """Genera el plan de reparación determinista a partir de la deriva.

    - Un doc que falta en grafo y/o vector → un solo `reindex` (re-procesar en LightRAG).
    - Un id huérfano en grafo → `delete_orphan_graph`.
    - Un id huérfano en vector → `delete_orphan_vector`.
    """
    actions: list = []
    for doc_id in sorted(drift.missing_in_graph | drift.missing_in_vector):
        actions.append(RepairAction("reindex", doc_id))
    for doc_id in sorted(drift.orphan_in_graph):
        actions.append(RepairAction("delete_orphan_graph", doc_id))
    for doc_id in sorted(drift.orphan_in_vector):
        actions.append(RepairAction("delete_orphan_vector", doc_id))
    return actions


# --- Lectores de backend (I/O real; se mockean en tests) -------------------
class DocIdReader(Protocol):
    def doc_ids(self) -> set: ...
    def delete(self, doc_id: str) -> None: ...
    def ping(self) -> bool: ...


class Supervisor:
    """Ata health-gate + saga + reconciliación contra backends reales.

    Recibe por inyección un cliente de LightRAG (fuente de verdad de docs procesados y
    reindexado) y dos lectores de doc_ids (grafo=Neo4j, vector=Postgres). Toda la
    orquestación es testeable pasando dobles; solo los lectores concretos hacen I/O.
    """

    def __init__(self, lightrag, graph_reader, vector_reader, max_retries: int = 3, sleep=None):
        self.lightrag = lightrag
        self.graph = graph_reader
        self.vector = vector_reader
        self.max_retries = max_retries
        self.sleep = sleep

    def health_checks(self) -> dict:
        return {
            "lightrag": self.lightrag.ping,
            "neo4j": self.graph.ping,
            "postgres": self.vector.ping,
        }

    def verify(self) -> Drift:
        """Calcula la deriva actual entre docs procesados, grafo y vectores."""
        expected = self.lightrag.processed_doc_ids()
        return alignment_diff(expected, self.graph.doc_ids(), self.vector.doc_ids())

    def reconcile(self, apply: bool = False) -> dict:
        """Detecta deriva y (si apply=True) la repara. Devuelve un resumen serializable."""
        ok, faltan = health_gate(self.health_checks())
        if not ok:
            return {"ok": False, "motivo": f"backends no disponibles: {faltan}", "acciones": []}
        drift = self.verify()
        plan = repair_plan(drift)
        applied = []
        if apply:
            for action in plan:
                self._apply(action)
                applied.append({"kind": action.kind, "doc_id": action.doc_id})
        return {
            "ok": True,
            "alineado": drift.is_aligned(),
            "resumen": drift.summary(),
            "acciones": [{"kind": a.kind, "doc_id": a.doc_id} for a in plan],
            "aplicadas": applied,
        }

    def _apply(self, action: RepairAction) -> None:
        if action.kind == "reindex":
            self.lightrag.reindex(action.doc_id)
        elif action.kind == "delete_orphan_graph":
            self.graph.delete(action.doc_id)
        elif action.kind == "delete_orphan_vector":
            self.vector.delete(action.doc_id)
