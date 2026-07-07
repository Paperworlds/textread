import dataclasses
from pathlib import Path

import yaml


_CONFIG_PATH = Path("~/.local/paperworlds/textread/config.yaml")
_KNOWN_FIELDS = {"cache_root", "default_model", "context_path", "agent_enabled", "agent_backend", "default_profile", "pdf_backend", "raindrop_token", "raindrop_collection", "raindrop_digested_collection", "raindrop_blocked_collection", "raindrop_must_open_collection", "learnings_path", "nitter_instance", "twitter_cookie", "rss_sources", "rss_active_work", "python_weekly_cookie"}


@dataclasses.dataclass
class TextreadConfig:
    cache_root: str = "~/.local/paperworlds/textread/cache"
    default_model: str = "haiku"
    context_path: str = "~/.local/paperworlds/textread/read-context.yaml"
    agent_enabled: bool = True
    agent_backend: str = "sdk"
    default_profile: str = "default"
    pdf_backend: str = "native"
    raindrop_token: str | None = None
    raindrop_collection: str = "textread"
    raindrop_digested_collection: str = "digested"
    raindrop_blocked_collection: str = "blocked"
    raindrop_must_open_collection: str = "must-open"
    learnings_path: str = "~/.local/paperworlds/learnings"
    nitter_instance: str = "https://nitter.privacydev.net"
    twitter_cookie: str | None = None
    rss_sources: list = dataclasses.field(default_factory=list)
    rss_active_work: list = dataclasses.field(default_factory=list)
    python_weekly_cookie: str | None = None


def load() -> TextreadConfig:
    path = _CONFIG_PATH.expanduser()
    if not path.exists():
        return TextreadConfig()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        print("[WARN] textread.yaml is malformed — using defaults")
        return TextreadConfig()
    known = {k: v for k, v in data.items() if k in _KNOWN_FIELDS}
    # Cast agent_enabled to bool explicitly
    if "agent_enabled" in known:
        known["agent_enabled"] = bool(known["agent_enabled"])
    # Validate agent_backend
    if "agent_backend" in known and known["agent_backend"] not in {"sdk", "cli"}:
        print(f"[WARN] agent_backend must be 'sdk' or 'cli' — got {known['agent_backend']!r}, defaulting to 'sdk'")
        known["agent_backend"] = "sdk"
    if "pdf_backend" in known and known["pdf_backend"] not in {"native", "marker"}:
        print(f"[WARN] pdf_backend must be 'native' or 'marker' — got {known['pdf_backend']!r}, defaulting to 'native'")
        known["pdf_backend"] = "native"
    return TextreadConfig(**known)


def save(cfg: TextreadConfig) -> None:
    path = _CONFIG_PATH.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(dataclasses.asdict(cfg), default_flow_style=False))
