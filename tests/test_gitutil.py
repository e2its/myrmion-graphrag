from codebase_mcp import gitutil


def test_git_basics(tmp_git_repo):
    repo, git = tmp_git_repo
    sha = gitutil.current_sha(repo)
    assert len(sha) == 40
    assert gitutil.current_branch(repo) in ("master", "main")
    assert gitutil.commit_time(repo)
    assert gitutil.is_dirty(repo) is False


def test_changed_files(tmp_git_repo):
    repo, git = tmp_git_repo
    first = gitutil.current_sha(repo)
    (repo / "a.py").write_text("def uno():\n    return 2\n")
    (repo / "b.py").write_text("def dos():\n    return 2\n")
    assert set(gitutil.changed_files(first, cwd=repo)) == {"a.py", "b.py"}
    assert gitutil.is_dirty(repo) is True


def test_no_repo(tmp_path):
    assert gitutil.current_sha(tmp_path) == ""
    assert gitutil.current_branch(tmp_path) == ""
    assert gitutil.changed_files("HEAD", cwd=tmp_path) == []
