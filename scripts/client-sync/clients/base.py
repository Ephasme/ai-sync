"""Abstract Client interface. Each implementation holds paths, formats, and derivation logic."""
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path


class Client(ABC):
    """Adapter for a specific AI client. Holds where to put things, structure, and derivation logic."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Client id (codex, cursor, gemini)."""
        ...

    @property
    @abstractmethod
    def config_dir(self) -> Path:
        """Base config directory (e.g. ~/.codex)."""
        ...

    def get_agents_dir(self) -> Path:
        return self.config_dir / "agents"

    def get_skills_dir(self) -> Path:
        return self.config_dir / "skills"

    @abstractmethod
    def write_agent(
        self,
        slug: str,
        meta: dict,
        raw_content: str,
        prompt_src_path: Path,
    ) -> None:
        """Write agent file(s) for this client. Uses slug, meta, raw_content, and source prompt path."""
        ...

    @abstractmethod
    def sync_mcp(self, servers: dict, secrets: dict, for_client: Callable[[dict, str], bool]) -> None:
        """Update this client's MCP config. for_client(srv, self.name) filters servers."""
        ...

    @abstractmethod
    def sync_client_config(self, settings: dict) -> None:
        """Apply generic settings.yaml to this client's config."""
        ...

    def get_oauth_src_path(self) -> Path | None:
        """Path to OAuth token cache on client (for capture). None if not supported."""
        return None

    def get_oauth_stash_filename(self) -> str | None:
        """Filename in config/mcp-servers/secrets/ for captured OAuth cache. None if not supported."""
        return None
