import dataclasses
from pathlib import Path

import yaml


_CONFIG_PATH = Path("~/.config/paperworlds/textread.yaml")
_KNOWN_FIELDS = {"cache_root", "default_model", "context_path", "agent_enabled", "agent_backend"}


@dataclasses.dataclass
class TextreadConfig:
    cache_root: str = "~/.textread/cache"
    default_model: str = "haiku"
    context_path: str = "~/.config/paperworlds/read-context.yaml"
    agent_enabled: bool = True
    agent_backend: str = "sdk"


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
    return TextreadConfig(**known)


def save(cfg: TextreadConfig) -> None:
    path = _CONFIG_PATH.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(dataclasses.asdict(cfg), default_flow_style=False))
