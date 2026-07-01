import pathlib
import subprocess

import pytest

from codebase_mcp import indexer, resolver
from codebase_mcp.graph import InMemoryGraphStore
from codebase_mcp.parser.python_ast import PythonAstParser

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
MINI = FIXTURES / "mini_codebase"


@pytest.fixture
def mem_store():
    return InMemoryGraphStore()


@pytest.fixture
def mini_codebase():
    return MINI


@pytest.fixture
def py_graph():
    """Grafo Python conocido (util/svc/app/orphan) ya resuelto en un InMemoryGraphStore."""
    p = PythonAstParser()
    nodes, edges = [], []
    for name in ("util.py", "svc.py", "app.py", "orphan.py"):
        res = p.parse_source((MINI / name).read_text(), name)
        nodes += res.nodes
        edges += res.edges
    edges = resolver.resolve_all(nodes, edges)
    store = InMemoryGraphStore()
    store.upsert_many(nodes, [])
    store.replace_edges(edges)
    return store


@pytest.fixture
def indexed_store(mem_store, tmp_path):
    """Indexa solo los .py del mini_codebase en un dir temporal (sin fixtures de otros langs)."""
    root = tmp_path / "code"
    root.mkdir()
    for name in ("util.py", "svc.py", "app.py", "orphan.py"):
        (root / name).write_text((MINI / name).read_text())
    indexer.index(mem_store, root)
    return mem_store, root


@pytest.fixture
def tmp_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")
    (repo / "a.py").write_text("def uno():\n    return 1\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    return repo, git
