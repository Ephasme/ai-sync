from __future__ import annotations

from dataclasses import dataclass

from ai_sync.display.plain import PlainDisplay
from ai_sync.display.rich import RichDisplay
from ai_sync.interactive import run_interactive_prompts


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


def test_run_interactive_prompts_ok(monkeypatch) -> None:
    results = [DummyPrompt(["a"]), DummyPrompt(["s"])]

    def _next_checkbox(*_args, **_kwargs):
        return results.pop(0)

    monkeypatch.setattr("questionary.checkbox", _next_checkbox)
    monkeypatch.setattr("questionary.confirm", lambda *_args, **_kwargs: DummyPrompt(True))
    display = PlainDisplay()
    opts = run_interactive_prompts(display, ["a"], ["s"])
    assert opts is not None
    assert "a" in opts.agent_stems
    assert "s" in opts.skill_names
    assert opts.install_settings is True


def test_run_interactive_prompts_cancel(monkeypatch) -> None:
    monkeypatch.setattr("questionary.checkbox", lambda *_args, **_kwargs: DummyPrompt(None))
    display = PlainDisplay()
    assert run_interactive_prompts(display, ["a"], ["s"]) is None
