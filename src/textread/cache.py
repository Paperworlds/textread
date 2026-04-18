import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

import click
import yaml

from textread.config import TextreadConfig, load as load_config


class CacheError(Exception):
    """Raised when cache operations fail."""


def _slug(url: str) -> str:
    """Derive slug+hash from URL.

    Returns string of form {slug}-{hash6} where:
    - slug is derived from URL path, alphanumeric with dashes
    - hash6 is first 6 chars of SHA-256(url)
    """
    # Extract path component from URL
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path.strip("/")

    # Replace non-alphanumeric with dash, collapse runs, strip edges
    slug_text = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")

    # Truncate to 40 chars
    slug_text = slug_text[:40]

    # Hash the full URL
    hash_full = hashlib.sha256(url.encode()).hexdigest()
    hash6 = hash_full[:6]

    return f"{slug_text}-{hash6}" if slug_text else f"root-{hash6}"


def path(url: str, cfg: Optional[TextreadConfig] = None) -> Path:
    """Return cache directory path for URL.

    Args:
        url: The URL to cache
        cfg: Optional TextreadConfig. If None, loads from defaults.

    Returns:
        Path object for the cache directory (not created)
    """
    if cfg is None:
        cfg = load_config()
    cache_root = Path(cfg.cache_root).expanduser()
    return cache_root / _slug(url)


def exists(url: str, cfg: Optional[TextreadConfig] = None) -> bool:
    """Check if cache entry exists for URL.

    Returns True iff {cache_path}/raw.meta.json exists.
    """
    cache_path = path(url, cfg)
    return (cache_path / "raw.meta.json").exists()


def put(url: str, result: Any, cfg: Optional[TextreadConfig] = None) -> Path:
    """Write FetchResult to cache.

    Expects result to have: url, final_url, text, content_type, fetched_at

    Creates:
    - raw.html or raw.txt (depending on content_type)
    - raw.md (the extracted article text)
    - raw.meta.json (metadata dict)

    Args:
        url: The URL that was fetched
        result: FetchResult object with url, final_url, text, content_type, fetched_at
        cfg: Optional TextreadConfig

    Returns:
        Path to the cache directory
    """
    cache_path = path(url, cfg)
    cache_path.mkdir(parents=True, exist_ok=True)

    # Determine file extension based on content_type
    extension = "html" if "text/html" in result.content_type else "txt"

    # Write raw file (original fetched content)
    raw_file = cache_path / f"raw.{extension}"
    raw_file.write_text(result.text, encoding="utf-8")

    # Write markdown file (extracted article text)
    md_file = cache_path / "raw.md"
    md_file.write_text(result.text, encoding="utf-8")

    # Write metadata
    meta_dict = {
        "url": result.url,
        "final_url": result.final_url,
        "content_type": result.content_type,
        "fetched_at": result.fetched_at,
    }
    meta_file = cache_path / "raw.meta.json"
    meta_file.write_text(json.dumps(meta_dict, indent=2), encoding="utf-8")

    return cache_path


def get_meta(url: str, cfg: Optional[TextreadConfig] = None) -> dict:
    """Load metadata for cached URL.

    Raises CacheError if cache entry doesn't exist.
    """
    cache_path = path(url, cfg)
    meta_file = cache_path / "raw.meta.json"

    if not meta_file.exists():
        raise CacheError(f"Cache entry not found for {url}")

    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise CacheError(f"Failed to read metadata for {url}: {e}")


def get_raw(url: str, cfg: Optional[TextreadConfig] = None) -> str:
    """Load raw file content for cached URL.

    Tries raw.html first, then raw.txt.
    Raises CacheError if cache entry doesn't exist.
    """
    cache_path = path(url, cfg)

    # Try html first
    html_file = cache_path / "raw.html"
    if html_file.exists():
        try:
            return html_file.read_text(encoding="utf-8")
        except OSError as e:
            raise CacheError(f"Failed to read raw.html for {url}: {e}")

    # Try txt
    txt_file = cache_path / "raw.txt"
    if txt_file.exists():
        try:
            return txt_file.read_text(encoding="utf-8")
        except OSError as e:
            raise CacheError(f"Failed to read raw.txt for {url}: {e}")

    raise CacheError(f"Cache entry not found for {url}")


def get_markdown(url: str, cfg: Optional[TextreadConfig] = None) -> str:
    """Load markdown file for cached URL.

    Raises CacheError if cache entry doesn't exist.
    """
    cache_path = path(url, cfg)
    md_file = cache_path / "raw.md"

    if not md_file.exists():
        raise CacheError(f"Cache entry not found for {url}")

    try:
        return md_file.read_text(encoding="utf-8")
    except OSError as e:
        raise CacheError(f"Failed to read raw.md for {url}: {e}")


def write_mapping(url: str, mapping: dict, cfg: Optional[TextreadConfig] = None) -> None:
    """Write mapping dict to mapping.yaml for URL.

    Creates the cache directory if it doesn't exist.
    """
    cache_path = path(url, cfg)
    cache_path.mkdir(parents=True, exist_ok=True)

    mapping_file = cache_path / "mapping.yaml"
    mapping_file.write_text(yaml.dump(mapping, default_flow_style=False), encoding="utf-8")


def read_mapping(url: str, cfg: Optional[TextreadConfig] = None) -> Optional[dict]:
    """Read mapping dict from mapping.yaml for URL.

    Returns None if mapping.yaml doesn't exist.
    Raises CacheError on parse errors.
    """
    cache_path = path(url, cfg)
    mapping_file = cache_path / "mapping.yaml"

    if not mapping_file.exists():
        return None

    try:
        data = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        return data if data is not None else {}
    except yaml.YAMLError as e:
        raise CacheError(f"Failed to parse mapping.yaml for {url}: {e}")
    except OSError as e:
        raise CacheError(f"Failed to read mapping.yaml for {url}: {e}")


@click.group(name="cache")
def cache_group():
    """Manage cache."""


@cache_group.command("list")
def list_cache():
    """List all cached entries."""
    cfg = load_config()
    cache_root = Path(cfg.cache_root).expanduser()

    if not cache_root.exists():
        click.echo("Cache is empty.")
        return

    # Glob all raw.meta.json files
    meta_files = sorted(cache_root.glob("*/raw.meta.json"))

    if not meta_files:
        click.echo("Cache is empty.")
        return

    for meta_file in meta_files:
        try:
            meta_dict = json.loads(meta_file.read_text(encoding="utf-8"))
            dir_name = meta_file.parent.name
            url = meta_dict.get("url", "unknown")
            fetched_at = meta_dict.get("fetched_at", "unknown")
            click.echo(f"{dir_name}  {url}  {fetched_at}")
        except (json.JSONDecodeError, OSError, KeyError):
            # Skip entries with bad metadata
            pass


@cache_group.command("path")
@click.argument("url")
def cache_path(url: str):
    """Print absolute cache path for URL."""
    cache_dir = path(url)
    click.echo(str(cache_dir))


@cache_group.command("clear")
def clear_cache():
    """Delete all cache entries."""
    cfg = load_config()
    cache_root = Path(cfg.cache_root).expanduser()

    if not cache_root.exists():
        click.echo("0")
        return

    # Count and delete all entries
    count = 0
    for entry in cache_root.glob("*"):
        if entry.is_dir():
            import shutil

            shutil.rmtree(entry)
            count += 1

    click.echo(count)
