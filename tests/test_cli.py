from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from ai_sync import cli
from ai_sync.display import PlainDisplay


@pytest.fixture()
def display() -> PlainDisplay:
    return PlainDisplay()



def test_run_install_writes_config(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    args = argparse.Namespace(op_account="Test", force=True)
    assert cli._run_install(args, display) == 0
    config_path = tmp_path / "config.toml"
    assert config_path.exists()
    assert "op_account" in config_path.read_text(encoding="utf-8")


def test_run_install_requires_op_account(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    monkeypatch.setattr(cli, "ensure_layout", lambda: tmp_path)
    monkeypatch.delenv("OP_ACCOUNT", raising=False)
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    args = argparse.Namespace(op_account=None, force=True)
    assert cli._run_install(args, display) == 1


def test_run_import_local_path_links_in_place(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    """Local paths are referenced directly — not copied into the store."""
    repo = tmp_path / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / "prompts" / "agent.md").write_text("hi", encoding="utf-8")
    (repo / "skills" / "skill-one").mkdir(parents=True)
    (repo / "skills" / "skill-one" / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (repo / "mcp-servers.yaml").write_text("servers:\n  ok:\n    method: stdio\n    command: npx\n", encoding="utf-8")
    (repo / "defaults.yaml").write_text("agents: []\n", encoding="utf-8")
    (repo / ".env.tpl").write_text("X=1\n", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(cli, "ensure_layout", lambda: dest)
    args = argparse.Namespace(repo=str(repo), name="my-repo", force=False)
    assert cli._run_import(args, display) == 0

    # Nothing should be copied into the store
    assert not (dest / "repos" / "my-repo").exists()

    # repos.yaml stores the structured entry with the absolute path as source
    import yaml as _yaml
    repos_data = _yaml.safe_load((dest / "repos.yaml").read_text())
    abs_repo = str(repo.resolve())
    assert {"name": "my-repo", "source": abs_repo} in repos_data["repos"]

    # get_all_repo_roots returns the original directory directly
    from ai_sync.repo_store import get_all_repo_roots
    roots = get_all_repo_roots(dest)
    assert len(roots) == 1
    assert roots[0] == repo.resolve()
    assert (roots[0] / "prompts" / "agent.md").exists()


def test_run_import_second_repo_warns_about_defaults(monkeypatch, tmp_path: Path) -> None:
    from ai_sync.display import PlainDisplay as _PD

    class CapturingDisplay(_PD):
        def __init__(self) -> None:
            self.messages: list[str] = []

        def print(self, msg: str, style: str = "normal") -> None:
            self.messages.append(msg)

        def panel(self, content: str, *, title: str = "", style: str = "normal") -> None:
            self.messages.append(content)

    dest = tmp_path / "dest"
    dest.mkdir()
    first_repo_store = dest / "repos" / "first-repo"
    first_repo_store.mkdir(parents=True)
    (first_repo_store / "defaults.yaml").write_text("agents: []\n", encoding="utf-8")
    import yaml as _yaml
    (dest / "repos.yaml").write_text(
        _yaml.safe_dump(
            {"repos": [{"name": "first-repo", "source": "https://example.com/first-repo.git"}]}
        )
    )

    repo = tmp_path / "second-repo"
    repo.mkdir()
    (repo / "prompts").mkdir()
    cap = CapturingDisplay()
    monkeypatch.setattr(cli, "ensure_layout", lambda: dest)
    args = argparse.Namespace(repo=str(repo), name="second-repo", force=False)
    result = cli._run_import(args, cap)
    assert result == 0
    assert any("first-repo" in m for m in cap.messages)


def test_run_doctor_missing_config(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    monkeypatch.setattr(cli, "get_config_root", lambda: tmp_path)
    assert cli._run_doctor(tmp_path, display) == 1


def test_run_doctor_ok(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    monkeypatch.setattr(cli, "get_config_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "find_project_root", lambda: None)
    (tmp_path / "config.toml").write_text("op_account = \"X\"\n", encoding="utf-8")
    repo_dir = tmp_path / "repos" / "my-config"
    repo_dir.mkdir(parents=True)
    import yaml as _yaml
    (tmp_path / "repos.yaml").write_text(
        _yaml.safe_dump(
            {"repos": [{"name": "my-config", "source": "https://example.com/my-config.git"}]}
        )
    )
    monkeypatch.setenv("OP_ACCOUNT", "X")
    assert cli._run_doctor(tmp_path, display) == 0


def test_run_import_fails_on_duplicate_name(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    """Importing with the same name twice without --force returns 1."""
    repo = tmp_path / "repo"
    repo.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(cli, "ensure_layout", lambda: dest)

    args = argparse.Namespace(repo=str(repo), name="my-repo", force=False)
    assert cli._run_import(args, display) == 0

    args2 = argparse.Namespace(repo=str(repo), name="my-repo", force=False)
    assert cli._run_import(args2, display) == 1


def test_run_import_force_overwrites(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    """Importing with --force over an existing name succeeds and updates the entry."""
    repo_v1 = tmp_path / "repo-v1"
    repo_v1.mkdir()
    repo_v2 = tmp_path / "repo-v2"
    repo_v2.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(cli, "ensure_layout", lambda: dest)

    args = argparse.Namespace(repo=str(repo_v1), name="my-repo", force=False)
    assert cli._run_import(args, display) == 0

    args2 = argparse.Namespace(repo=str(repo_v2), name="my-repo", force=True)
    assert cli._run_import(args2, display) == 0

    import yaml as _yaml
    repos_data = _yaml.safe_load((dest / "repos.yaml").read_text())
    entries = repos_data["repos"]
    assert len(entries) == 1
    assert entries[0]["name"] == "my-repo"
    assert entries[0]["source"] == str(repo_v2.resolve())


def test_run_import_force_cleans_up_remote_copy(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    """--force over a previously-cloned remote entry removes the stored copy."""
    dest = tmp_path / "dest"
    dest.mkdir()
    # Simulate an existing stored-copy repo (source is a URL, not a local path).
    stored_copy = dest / "repos" / "my-repo"
    stored_copy.mkdir(parents=True)
    (stored_copy / "old.md").write_text("old content", encoding="utf-8")
    import yaml as _yaml
    (dest / "repos.yaml").write_text(
        _yaml.safe_dump({"repos": [{"name": "my-repo", "source": "https://example.com/old.git"}]})
    )
    monkeypatch.setattr(cli, "ensure_layout", lambda: dest)

    # Force-import a local path under the same name.
    local_repo = tmp_path / "new-local"
    local_repo.mkdir()
    args = argparse.Namespace(repo=str(local_repo), name="my-repo", force=True)
    assert cli._run_import(args, display) == 0

    # Old stored copy must be gone.
    assert not stored_copy.exists()

    # Entry updated to local source.
    repos_data = _yaml.safe_load((dest / "repos.yaml").read_text())
    entries = repos_data["repos"]
    assert len(entries) == 1
    assert entries[0]["source"] == str(local_repo.resolve())


def test_run_import_invalid_slug(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    """Invalid slug names return 1 without touching repos.yaml."""
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(cli, "ensure_layout", lambda: dest)

    for bad_name in ["Team/Config", "my_config", "-bad", "bad-"]:
        repo = tmp_path / "repo"
        repo.mkdir(exist_ok=True)
        args = argparse.Namespace(repo=str(repo), name=bad_name, force=False)
        assert cli._run_import(args, display) == 1, f"Expected 1 for name={bad_name!r}"



def test_run_apply_success(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    import yaml as _yaml
    config_root = tmp_path / "root"
    config_root.mkdir()
    (config_root / "config.toml").write_text("op_account = \"x\"\n", encoding="utf-8")
    repo_dir = config_root / "repos" / "my-config"
    repo_dir.mkdir(parents=True)
    (repo_dir / "mcp-servers.yaml").write_text("servers: {}\n", encoding="utf-8")
    (config_root / "repos.yaml").write_text(
        _yaml.safe_dump(
            {"repos": [{"name": "my-config", "source": "https://example.com/my-config.git"}]}
        )
    )
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".ai-sync.yaml").write_text("agents: []\nskills: []\n", encoding="utf-8")

    monkeypatch.setattr(cli, "find_project_root", lambda: project_root)
    monkeypatch.setattr(cli, "run_apply", lambda **kwargs: 0)
    args = argparse.Namespace(plain=True)
    assert cli._run_apply(args, config_root, display) == 0


def test_run_init_zero_repos(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root = tmp_path / "root"
    config_root.mkdir()
    (config_root / "config.toml").write_text("op_account = \"x\"\n", encoding="utf-8")
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    args = argparse.Namespace(tag=None)
    assert cli._run_init(args, config_root, display) == 1


def test_build_parser_has_install_apply_init() -> None:
    parser = cli._build_parser()
    for cmd in ("install", "apply", "init", "import", "doctor", "uninstall"):
        result = parser.parse_args(
            [cmd] if cmd != "import" else [cmd, "--repo", "/tmp", "--name", "x"]
        )
        assert result.command == cmd


def test_build_parser_init_tag() -> None:
    parser = cli._build_parser()
    result = parser.parse_args(["init", "--tag", "dev,edito"])
    assert result.tag == "dev,edito"


def _make_registry(tmp_path: Path) -> Path:
    """Create a config_root with one imported repo in the new multi-repo layout."""
    config_root = tmp_path / "root"
    config_root.mkdir(parents=True)
    (config_root / "config.toml").write_text("op_account = \"x\"\n", encoding="utf-8")

    repo_dir = config_root / "repos" / "my-config"

    prompts_dir = repo_dir / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "agent_a.md").write_text("# A", encoding="utf-8")
    (prompts_dir / "agent_a.metadata.yaml").write_text("tags: [dev]\n", encoding="utf-8")
    (prompts_dir / "agent_b.md").write_text("# B", encoding="utf-8")
    (prompts_dir / "agent_b.metadata.yaml").write_text("tags: [edito]\n", encoding="utf-8")
    (prompts_dir / "agent_c.md").write_text("# C", encoding="utf-8")

    skills_dir = repo_dir / "skills"
    (skills_dir / "skill-dev").mkdir(parents=True)
    (skills_dir / "skill-dev" / "SKILL.md").write_text("# Skill", encoding="utf-8")
    (skills_dir / "skill-dev" / "metadata.yaml").write_text("tags: [dev]\n", encoding="utf-8")
    (skills_dir / "skill-other").mkdir(parents=True)
    (skills_dir / "skill-other" / "SKILL.md").write_text("# Other", encoding="utf-8")

    commands_dir = repo_dir / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "cmd_dev.md").write_text("# Cmd", encoding="utf-8")
    (commands_dir / "cmd_dev.metadata.yaml").write_text("tags: [dev]\n", encoding="utf-8")
    (commands_dir / "cmd_plain.md").write_text("# Plain", encoding="utf-8")

    (repo_dir / "mcp-servers.yaml").write_text(
        "servers:\n"
        "  srv-dev:\n"
        "    method: stdio\n"
        "    command: npx\n"
        "    tags: [dev]\n"
        "  srv-plain:\n"
        "    method: stdio\n"
        "    command: npx\n",
        encoding="utf-8",
    )

    import yaml as _yaml
    (config_root / "repos.yaml").write_text(
        _yaml.safe_dump(
            {"repos": [{"name": "my-config", "source": "https://example.com/my-config.git"}]}
        )
    )

    return config_root


def test_discover_artifact_tags(tmp_path: Path) -> None:
    from ai_sync.repo_store import get_all_repo_roots
    config_root = _make_registry(tmp_path)
    repo_roots = get_all_repo_roots(config_root)
    tags = cli._discover_artifact_tags(repo_roots)
    assert tags["agents"]["agent_a"] == ["dev"]
    assert tags["agents"]["agent_b"] == ["edito"]
    assert "agent_c" not in tags["agents"]
    assert tags["skills"]["skill-dev"] == ["dev"]
    assert "skill-other" not in tags["skills"]
    assert tags["commands"]["cmd_dev.md"] == ["dev"]
    assert "cmd_plain.md" not in tags["commands"]
    assert tags["mcp-servers"]["srv-dev"] == ["dev"]
    assert "srv-plain" not in tags["mcp-servers"]


def test_filter_by_tags() -> None:
    artifact_tags = {"a": ["dev"], "b": ["edito"], "c": ["dev", "edito"], "d": []}
    assert cli._filter_by_tags(["a", "b", "c", "d"], artifact_tags, {"dev"}) == ["a", "c"]
    assert cli._filter_by_tags(["a", "b", "c", "d"], artifact_tags, {"edito"}) == ["b", "c"]
    assert cli._filter_by_tags(["a", "b", "c", "d"], artifact_tags, {"dev", "edito"}) == ["a", "b", "c"]
    assert cli._filter_by_tags(["a", "b", "c", "d"], artifact_tags, {"other"}) == []


def test_run_init_with_tag(monkeypatch, tmp_path: Path, display: PlainDisplay) -> None:
    config_root = _make_registry(tmp_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(cli, "write_gitignore_entries", lambda *a, **kw: None)

    args = argparse.Namespace(tag="dev")
    assert cli._run_init(args, config_root, display) == 0

    import yaml as _yaml
    manifest = _yaml.safe_load((project_root / ".ai-sync.yaml").read_text(encoding="utf-8"))
    assert "agent_a" in manifest["agents"]
    assert "agent_b" not in manifest["agents"]
    assert "agent_c" not in manifest["agents"]
    assert "skill-dev" in manifest["skills"]
    assert "skill-other" not in manifest["skills"]
    assert "cmd_dev.md" in manifest["commands"]
    assert "cmd_plain.md" not in manifest["commands"]
    assert "srv-dev" in manifest["mcp-servers"]
    assert "srv-plain" not in manifest["mcp-servers"]
