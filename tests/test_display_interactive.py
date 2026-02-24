from __future__ import annotations

from dataclasses import dataclass

from ai_sync.display.plain import PlainDisplay
from ai_sync.display.rich import RichDisplay
from ai_sync.interactive import run_init_prompts


def test_plain_display_methods() -> None:
    display = PlainDisplay()
    display.rule("Title")
    display.print("Hello")
    display.panel("Body", title="Panel")
    display.table(("A", "B"), [("1", "2")])


def test_rich_display_methods() -> None:
    display = RichDisplay()
    display.rule("Title")
    display.print("Hello")
    display.panel("Body", title="Panel")
    display.table(("A", "B"), [("1", "2")])


@dataclass
class DummyPrompt:
    result: object

    def ask(self):
        return self.result


def test_run_init_prompts_ok(monkeypatch) -> None:
    results = [
        DummyPrompt(["a"]),
        DummyPrompt(["s"]),
        DummyPrompt(["cmd"]),
        DummyPrompt(["mcp1"]),
        DummyPrompt("normal"),
        DummyPrompt(True),
        DummyPrompt(True),
        DummyPrompt(False),
    ]

    def _next(*_args, **_kwargs):
        return results.pop(0) if results else DummyPrompt(None)

    monkeypatch.setattr("questionary.checkbox", lambda *a, **k: _next())
    monkeypatch.setattr("questionary.select", lambda *a, **k: _next())
    monkeypatch.setattr("questionary.confirm", lambda *a, **k: _next())
    display = PlainDisplay()
    result = run_init_prompts(
        display,
        available_agents=["a"],
        available_skills=["s"],
        available_commands=["cmd"],
        available_mcp_servers=["mcp1"],
        defaults={},
    )
    assert result is not None
    assert "a" in result["agents"]
    assert "s" in result["skills"]
    assert "cmd" in result["commands"]
    assert "mcp1" in result["mcp-servers"]
    assert result["settings"]["mode"] == "normal"


def test_run_init_prompts_cancel(monkeypatch) -> None:
    monkeypatch.setattr("questionary.checkbox", lambda *a, **k: DummyPrompt(None))
    display = PlainDisplay()
    assert (
        run_init_prompts(
            display,
            available_agents=["a"],
            available_skills=["s"],
            available_commands=[],
            available_mcp_servers=[],
            defaults={},
        )
        is None
    )
