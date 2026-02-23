"""Configuration from environment variables."""
import os
import sys


class Config:
    """Load and validate configuration from env vars."""

    def __init__(self):
        self.bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id: int = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
        self.work_dir: str = os.environ.get("CLAUDE_WORK_DIR", os.getcwd())
        self.verbose: bool = os.environ.get("CLAUDE_TG_VERBOSE", "0") == "1"
        self.model: str | None = os.environ.get("CLAUDE_TG_MODEL")
        self.max_budget: float | None = (
            float(v) if (v := os.environ.get("CLAUDE_TG_MAX_BUDGET")) else None
        )
        self.session_timeout: int = int(
            os.environ.get("CLAUDE_TG_SESSION_TIMEOUT", "3600")
        )
        self.update_interval: float = float(
            os.environ.get("CLAUDE_TG_UPDATE_INTERVAL", "2.0")
        )
        self.groq_api_key: str | None = os.environ.get("GROQ_API_KEY")
        self.trigger_port: int = int(
            os.environ.get("CLAUDE_TG_TRIGGER_PORT", "0")
        )
        self.mcp_config: str | None = os.environ.get("CLAUDE_TG_MCP_CONFIG")
        exclude = os.environ.get("CLAUDE_TG_MCP_EXCLUDE", "")
        self.mcp_exclude: list[str] = [
            s.strip() for s in exclude.split(",") if s.strip()
        ]

    def validate(self) -> list[str]:
        """Return list of validation errors. Empty = valid."""
        errors = []
        if not self.bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required")
        if not self.chat_id:
            errors.append("TELEGRAM_CHAT_ID is required")
        if not os.path.isdir(self.work_dir):
            errors.append(f"CLAUDE_WORK_DIR '{self.work_dir}' is not a directory")
        return errors
