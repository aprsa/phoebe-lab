"""Configuration loader for PHOEBE Lab.

Deployment modes and their paths:

1. Editable install (pip install -e):
    - Config: <project_root>/config.toml
    - Examples: <project_root>/examples/

2. venv install (pip install):
    - Config: ~/.config/phoebe-lab/config.toml
    - Examples: ~/.local/share/phoebe-lab/examples/

3. System-wide install (sudo pip install) and Docker:
    - Config: /etc/phoebe-lab/config.toml
    - Examples: /usr/share/phoebe-lab/examples/

Uses built-in defaults if config file is missing (localhost:8001 for server, no password).
"""

from dataclasses import dataclass, field
from pathlib import Path
import sys
import tomllib


def _find_project_root() -> Path | None:
    """Walk up from this file looking for pyproject.toml (editable install)."""
    current = Path(__file__).parent.resolve()
    while True:
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent
    return None


def _in_virtualenv() -> bool:
    """Return True when running inside a virtual environment."""
    base_prefix = getattr(sys, "base_prefix", sys.prefix)
    return sys.prefix != base_prefix


# Determine deployment mode and set paths
_PROJECT_ROOT = _find_project_root()

if _PROJECT_ROOT is not None:
    # Editable install: pip install -e
    CONFIG_PATH = _PROJECT_ROOT / "config.toml"
    EXAMPLES_PATH = _PROJECT_ROOT / "examples"
elif _in_virtualenv():
    # venv install: user-local config/data
    CONFIG_PATH = Path.home() / ".config" / "phoebe-lab" / "config.toml"
    EXAMPLES_PATH = Path.home() / ".local" / "share" / "phoebe-lab" / "examples"
else:
    # System-wide install or Docker
    CONFIG_PATH = Path("/etc/phoebe-lab/config.toml")
    EXAMPLES_PATH = Path("/usr/share/phoebe-lab/examples")


@dataclass(frozen=True)
class ServerConfig:
    host: str = "localhost"
    port: int = 8001


@dataclass(frozen=True)
class AccessConfig:
    password: str = ""
    enabled: bool = False


@dataclass(frozen=True)
class UIConfig:
    host: str = "0.0.0.0"
    port: int = 80
    title: str = "PHOEBE Lab"
    reconnect_timeout: int = 300
    storage_secret: str = "phoebe-lab-secret-key-change-in-production"


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    access: AccessConfig = field(default_factory=AccessConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def _load_config() -> AppConfig:
    """Load config from CONFIG_PATH or use defaults if file is missing."""
    data = {}

    if CONFIG_PATH.is_file():
        try:
            with CONFIG_PATH.open("rb") as f:
                data = tomllib.load(f)
        except Exception:
            pass

    server_data = data.get("server", {})
    access_data = data.get("access", {})
    ui_data = data.get("ui", {})

    def get_args(config_cls, data):
        return {k: v for k, v in data.items() if v is not None and k in config_cls.__dataclass_fields__}

    return AppConfig(
        server=ServerConfig(**get_args(ServerConfig, server_data)),
        access=AccessConfig(**get_args(AccessConfig, access_data)),
        ui=UIConfig(**get_args(UIConfig, ui_data)),
    )


# Loaded at import time
CONFIG = _load_config()
