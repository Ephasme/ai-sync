#!/usr/bin/env python3
from pathlib import Path

try:
    import yaml
except Exception:
    yaml = None

ROOT = Path("/Users/loup/code/perso/ai-tools")

agents = len(list((ROOT / "config" / "prompts").glob("*.md")))
skills_dir = ROOT / "config" / "skills"
skills = 0
if skills_dir.exists():
    skills = sum(
        1 for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
    )

servers = 0
servers_path = ROOT / "config" / "mcp-servers" / "servers.yaml"
if yaml and servers_path.exists():
    try:
        with servers_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        servers = len((data.get("servers") or {}).keys())
    except Exception:
        servers = 0

print(f"agents={agents} skills={skills} servers={servers}")
