"""Local foundation for the marketing agent."""

from .config import AgentConfig, ConfigError, load_config
from .storage import Store

__all__ = ["AgentConfig", "ConfigError", "Store", "load_config"]
