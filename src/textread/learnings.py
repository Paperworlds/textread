"""Load and search learnings — small YAML files capturing past troubleshooting wins."""
from __future__ import annotations

from pathlib import Path

import yaml


def _expand_compendium(stem: str, data: dict, path: Path) -> list[dict]:
    """A compendium file has top-level keys mapping to lists of records (each with an id).
    Emit each sub-record as its own logical learning, tagged with the section name."""
    out: list[dict] = []
    for section, records in data.items():
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            rec_id = rec.get("id") or f"{section}-{len(out)}"
            title = rec.get("title") or rec.get("purpose") or rec_id
            if isinstance(title, str):
                title = title.strip().splitlines()[0] if title.strip() else rec_id
            tags = list(rec.get("tags") or []) + [section]
            entry = dict(rec)
            entry["_name"] = f"{stem}:{rec_id}"
            entry["_path"] = str(path)
            entry["_section"] = section
            entry["_synthetic"] = True
            entry["title"] = title
            entry["tags"] = tags
            out.append(entry)
    return out


def _load_one(path: Path) -> list[dict]:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    if data.get("title"):
        data["_name"] = path.stem
        data["_path"] = str(path)
        return [data]
    expanded = _expand_compendium(path.stem, data, path)
    if expanded:
        return expanded
    # Fallback: keep the bare file with the stem as name, even without a title
    data["_name"] = path.stem
    data["_path"] = str(path)
    return [data]


def load_all(root: str) -> list[dict]:
    """Recursively load all *.yaml files under root. Returns [] if root missing.
    Compendium files (top-level keys that are lists of records) are expanded."""
    base = Path(root).expanduser()
    if not base.exists():
        return []
    out: list[dict] = []
    for p in sorted(base.rglob("*.yaml")):
        out.extend(_load_one(p))
    return out


def find(root: str, name: str) -> dict | None:
    """Return a learning by _name (exact), then by record id (exact), then by title substring."""
    items = load_all(root)
    for item in items:
        if item.get("_name") == name:
            return item
    for item in items:
        if item.get("id") == name:
            return item
    needle = name.lower()
    for item in items:
        if needle in (item.get("title") or "").lower():
            return item
    return None


def _str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class _LearningDumper(yaml.SafeDumper):
    pass


_LearningDumper.add_representer(str, _str_representer)


def render(item: dict) -> str:
    """Render a learning to YAML text. For compendium sub-records, dumps the record dict;
    for whole-file learnings, reads the file from disk."""
    if item.get("_synthetic"):
        clean = {k: v for k, v in item.items() if not k.startswith("_")}
        return yaml.dump(clean, Dumper=_LearningDumper, sort_keys=False,
                         default_flow_style=False, allow_unicode=True, width=120)
    return Path(item["_path"]).read_text()


def search(root: str, query: str) -> list[dict]:
    """Return learnings whose title/tags/symptom/cause contain query (case-insensitive)."""
    needle = query.lower()
    out = []
    for item in load_all(root):
        hay = " ".join([
            item.get("title") or "",
            " ".join(item.get("tags") or []),
            item.get("symptom") or "",
            item.get("cause") or "",
        ]).lower()
        if needle in hay:
            out.append(item)
    return out


def summarize_for_agent(items: list[dict]) -> str:
    """Compact one-line-per-learning summary for injection into agent system prompt."""
    if not items:
        return ""
    lines = []
    for it in items:
        title = it.get("title") or it.get("_name")
        tags = ", ".join(it.get("tags") or [])
        lines.append(f"  - {title}" + (f" [{tags}]" if tags else ""))
    return "Known learnings (past troubleshooting notes the user has captured):\n" + "\n".join(lines)
