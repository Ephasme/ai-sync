"""Interactive prompts."""

from __future__ import annotations

from dataclasses import dataclass

from .display import Display


@dataclass
class SyncOptions:
    agent_stems: frozenset[str]
    skill_names: frozenset[str]
    install_settings: bool


def run_interactive_prompts(
    display: Display,
    agent_stems: list[str],
    skill_names: list[str],
) -> SyncOptions | None:
    import questionary

    display.print("")
    if agent_stems:
        display.panel("Space to toggle, Enter to confirm", title="Select agents to install", style="info")
        selected_agents = questionary.checkbox(
            "Agents", choices=[questionary.Choice(title=a, value=a, checked=True) for a in agent_stems]
        ).ask()
        if selected_agents is None:
            return None
    else:
        display.print("Agents: skipping (none found)", style="dim")
        selected_agents = []

    display.print("")
    if skill_names:
        display.panel("Space to toggle, Enter to confirm", title="Select skills to install", style="info")
        selected_skills = questionary.checkbox(
            "Skills", choices=[questionary.Choice(title=s, value=s, checked=True) for s in skill_names]
        ).ask()
        if selected_skills is None:
            return None
    else:
        display.print("Skills: skipping (none found)", style="dim")
        selected_skills = []

    display.print("")
    display.panel("", title="Sync options", style="info")
    install_settings = questionary.confirm("Install client settings (client-settings.yaml)?", default=True).ask()
    if install_settings is None:
        return None

    return SyncOptions(
        agent_stems=frozenset(selected_agents or []),
        skill_names=frozenset(selected_skills or []),
        install_settings=install_settings,
    )
