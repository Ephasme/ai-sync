"""Interactive prompts for ai-sync init."""

from __future__ import annotations

from typing import Any

from .display import Display


def run_init_prompts(
    display: Display,
    available_agents: list[str],
    available_skills: list[str],
    available_commands: list[str],
    available_mcp_servers: list[str],
    defaults: dict[str, Any],
) -> dict[str, Any] | None:
    import questionary

    default_agents = set(defaults.get("agents") or [])
    default_skills = set(defaults.get("skills") or [])
    default_commands = set(defaults.get("commands") or [])
    default_mcp = set(defaults.get("mcp-servers") or [])
    default_settings = defaults.get("settings") or {}

    display.print("")
    if available_agents:
        display.panel("Space to toggle, Enter to confirm", title="Select agents", style="info")
        selected_agents = questionary.checkbox(
            "Agents",
            choices=[
                questionary.Choice(title=a, value=a, checked=(a in default_agents))
                for a in available_agents
            ],
        ).ask()
        if selected_agents is None:
            return None
    else:
        display.print("Agents: none available", style="dim")
        selected_agents = []

    display.print("")
    if available_skills:
        display.panel("Space to toggle, Enter to confirm", title="Select skills", style="info")
        selected_skills = questionary.checkbox(
            "Skills",
            choices=[
                questionary.Choice(title=s, value=s, checked=(s in default_skills))
                for s in available_skills
            ],
        ).ask()
        if selected_skills is None:
            return None
    else:
        display.print("Skills: none available", style="dim")
        selected_skills = []

    display.print("")
    if available_commands:
        display.panel("Space to toggle, Enter to confirm", title="Select commands", style="info")
        selected_commands = questionary.checkbox(
            "Commands",
            choices=[
                questionary.Choice(title=c, value=c, checked=(c in default_commands))
                for c in available_commands
            ],
        ).ask()
        if selected_commands is None:
            return None
    else:
        display.print("Commands: none available", style="dim")
        selected_commands = []

    display.print("")
    if available_mcp_servers:
        display.panel("Space to toggle, Enter to confirm", title="Select MCP servers", style="info")
        selected_mcp = questionary.checkbox(
            "MCP Servers",
            choices=[
                questionary.Choice(title=m, value=m, checked=(m in default_mcp))
                for m in available_mcp_servers
            ],
        ).ask()
        if selected_mcp is None:
            return None
    else:
        display.print("MCP Servers: none available", style="dim")
        selected_mcp = []

    display.print("")
    display.panel("", title="Client settings", style="info")
    mode = questionary.select(
        "Approval mode",
        choices=["normal", "strict", "yolo"],
        default=default_settings.get("mode", "normal"),
    ).ask()
    if mode is None:
        return None

    experimental = questionary.confirm(
        "Enable experimental features?",
        default=default_settings.get("experimental", True),
    ).ask()
    if experimental is None:
        return None

    subagents = questionary.confirm(
        "Enable subagents/multi-agent?",
        default=default_settings.get("subagents", True),
    ).ask()
    if subagents is None:
        return None

    tools_defaults = default_settings.get("tools") or {}
    sandbox = questionary.confirm(
        "Enable sandbox for tools?",
        default=tools_defaults.get("sandbox", False),
    ).ask()
    if sandbox is None:
        return None

    return {
        "agents": selected_agents or [],
        "skills": selected_skills or [],
        "commands": selected_commands or [],
        "mcp-servers": selected_mcp or [],
        "settings": {
            "mode": mode,
            "experimental": experimental,
            "subagents": subagents,
            "tools": {"sandbox": sandbox},
        },
    }
