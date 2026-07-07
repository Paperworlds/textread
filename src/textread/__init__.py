from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("textread")
except PackageNotFoundError:
    # Editable installs via uv may not generate dist-info — read pyproject.toml directly.
    try:
        from pathlib import Path
        import re as _re
        _pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
        _m = _re.search(r'^version\s*=\s*"([^"]+)"', _pyproject.read_text(), _re.MULTILINE)
        __version__ = _m.group(1) if _m else "unknown"
    except Exception:
        __version__ = "unknown"
