import pytest

import consistency
from consistency import (
    Drift,
    SagaError,
    SagaStep,
    alignment_diff,
    health_gate,
    repair_plan,
    run_saga,
)


def test_health_gate():
    ok, faltan = health_gate({"a": lambda: True, "b": lambda: True})
    assert ok and faltan == []
    ok, faltan = health_gate({"a": lambda: True, "b": lambda: False})
    assert not ok and faltan == ["b"]

    def boom():
        raise RuntimeError("x")
    ok, faltan = health_gate({"a": boom})
    assert not ok and faltan == ["a"]


def test_run_saga_success():
    log = []
    steps = [SagaStep("s1", lambda: log.append("s1")), SagaStep("s2", lambda: log.append("s2"))]
    assert run_saga(steps, sleep=lambda a: None) == ["s1", "s2"]
    assert log == ["s1", "s2"]


def test_run_saga_retry_then_success():
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("todavia no")

    done = run_saga([SagaStep("s", flaky)], max_retries=3, sleep=lambda a: None)
    assert done == ["s"] and state["n"] == 3


def test_run_saga_exhausted_compensates():
    comp = []
    steps = [
        SagaStep("s1", lambda: None, compensate=lambda: comp.append("undo1")),
        SagaStep("s2", action=_always_fail, compensate=lambda: comp.append("undo2")),
    ]
    with pytest.raises(SagaError) as ei:
        run_saga(steps, max_retries=2, sleep=lambda a: None)
    assert ei.value.step == "s2"
    assert comp == ["undo1"]  # solo s1 estaba completado


def _always_fail():
    raise RuntimeError("siempre falla")


def test_alignment_diff_y_repair_plan():
    drift = alignment_diff(
        expected={"d1", "d2", "d3"},
        in_graph={"d1", "d3", "huerG"},
        in_vector={"d1", "d2", "huerV"},
    )
    assert drift.missing_in_graph == {"d2"}
    assert drift.missing_in_vector == {"d3"}
    assert drift.orphan_in_graph == {"huerG"}
    assert drift.orphan_in_vector == {"huerV"}
    assert not drift.is_aligned()

    plan = repair_plan(drift)
    kinds = {(a.kind, a.doc_id) for a in plan}
    assert ("reindex", "d2") in kinds and ("reindex", "d3") in kinds
    assert ("delete_orphan_graph", "huerG") in kinds
    assert ("delete_orphan_vector", "huerV") in kinds


def test_drift_aligned():
    d = alignment_diff({"a"}, {"a"}, {"a"})
    assert d.is_aligned() and "ALINEADOS" in d.summary()


class _Fake:
    def __init__(self, ids, up=True):
        self.ids = set(ids)
        self.up = up
        self.deleted = []
        self.reindexed = []

    def ping(self):
        return self.up

    def processed_doc_ids(self):
        return set(self.ids)

    def doc_ids(self):
        return set(self.ids)

    def delete(self, d):
        self.deleted.append(d)

    def reindex(self, d):
        self.reindexed.append(d)


def test_supervisor_reconcile_aligned():
    lr = _Fake({"a", "b"})
    g = _Fake({"a", "b"})
    v = _Fake({"a", "b"})
    sup = consistency.Supervisor(lr, g, v)
    res = sup.reconcile(apply=False)
    assert res["ok"] and res["alineado"] and res["acciones"] == []


def test_supervisor_reconcile_repara():
    lr = _Fake({"a", "b"})     # esperados
    g = _Fake({"a"})           # falta b en grafo
    v = _Fake({"a", "b", "x"})  # x huérfano en vector
    sup = consistency.Supervisor(lr, g, v)
    res = sup.reconcile(apply=True)
    assert res["ok"] and not res["alineado"]
    assert lr.reindexed == ["b"]
    assert v.deleted == ["x"]


def test_supervisor_health_gate_aborta():
    sup = consistency.Supervisor(_Fake({}, up=False), _Fake({}), _Fake({}))
    res = sup.reconcile()
    assert res["ok"] is False and "no disponibles" in res["motivo"]
