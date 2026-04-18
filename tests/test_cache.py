import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from textread.cache import (
    CacheError,
    _slug,
    clear_cache,
    exists,
    get_markdown,
    get_meta,
    get_raw,
    path,
    put,
    read_mapping,
    write_mapping,
)
from textread.config import TextreadConfig


@dataclass
class FakeFetchResult:
    """Mock FetchResult for testing."""

    url: str
    final_url: str
    text: str
    content_type: str
    fetched_at: str


def make_config(cache_root: Path) -> TextreadConfig:
    """Create a TextreadConfig pointing to tmp_path."""
    return TextreadConfig(cache_root=str(cache_root))


class TestSlug:
    """Test slug derivation (R01)."""

    def test_slug_format(self):
        """Slug should be {slug-text}-{hash6}."""
        slug = _slug("https://example.com/path/to/article")
        # Should match pattern: text-hash
        assert re.match(r"^[a-z0-9\-]+-[a-f0-9]{6}$", slug)

    def test_slug_no_collision(self):
        """Different URLs should produce different slugs."""
        url1 = "https://example.com/article-1"
        url2 = "https://example.com/article-2"
        slug1 = _slug(url1)
        slug2 = _slug(url2)
        assert slug1 != slug2

    def test_slug_replaces_nonalpha(self):
        """Non-alphanumeric chars in path become dashes."""
        slug = _slug("https://example.com/path/to-my_article.html")
        assert "path" in slug
        assert "my" in slug
        assert "article" in slug
        # Should not contain underscores or dots from path
        parts = slug.split("-")
        assert all(p.isalnum() or p == "" for p in parts[:-1])

    def test_slug_handles_root_path(self):
        """URL with just domain gets 'root' prefix."""
        slug = _slug("https://example.com")
        assert slug.startswith("root-")


class TestPath:
    """Test path resolution."""

    def test_path_returns_cache_subdir(self, tmp_path):
        """path() should return {cache_root}/{slug}."""
        cfg = make_config(tmp_path)
        result = path("https://example.com/article", cfg)
        assert result.parent == tmp_path
        assert result.name == _slug("https://example.com/article")

    def test_path_uses_default_config(self, monkeypatch, tmp_path):
        """path() without cfg should use loaded config."""
        # Mock load_config in the cache module
        import textread.cache as cache_module

        def mock_load():
            return TextreadConfig(cache_root=str(tmp_path))

        monkeypatch.setattr(cache_module, "load_config", mock_load)
        result = path("https://example.com/test")
        assert result.parent == tmp_path


class TestExists:
    """Test cache existence check (R02)."""

    def test_exists_false_before_put(self, tmp_path):
        """exists() should return False before any write."""
        cfg = make_config(tmp_path)
        assert not exists("https://example.com/article", cfg)

    def test_exists_true_after_put(self, tmp_path):
        """exists() should return True after put()."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        result = FakeFetchResult(
            url=url,
            final_url=url,
            text="Article content",
            content_type="text/html",
            fetched_at="2026-04-18T10:00:00Z",
        )
        put(url, result, cfg)
        assert exists(url, cfg)


class TestPut:
    """Test cache write operations (R03)."""

    def test_put_creates_raw_html(self, tmp_path):
        """put() should create raw.html for HTML content."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        result = FakeFetchResult(
            url=url,
            final_url=url,
            text="<html>content</html>",
            content_type="text/html; charset=utf-8",
            fetched_at="2026-04-18T10:00:00Z",
        )
        cache_path = put(url, result, cfg)
        assert (cache_path / "raw.html").exists()
        assert (cache_path / "raw.html").read_text() == "<html>content</html>"

    def test_put_creates_raw_txt(self, tmp_path):
        """put() should create raw.txt for non-HTML content."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article.txt"
        result = FakeFetchResult(
            url=url,
            final_url=url,
            text="Plain text",
            content_type="text/plain",
            fetched_at="2026-04-18T10:00:00Z",
        )
        cache_path = put(url, result, cfg)
        assert (cache_path / "raw.txt").exists()
        assert (cache_path / "raw.txt").read_text() == "Plain text"

    def test_put_creates_raw_md(self, tmp_path):
        """put() should create raw.md with extracted text."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        extracted_text = "Extracted article markdown"
        result = FakeFetchResult(
            url=url,
            final_url=url,
            text=extracted_text,
            content_type="text/html",
            fetched_at="2026-04-18T10:00:00Z",
        )
        cache_path = put(url, result, cfg)
        assert (cache_path / "raw.md").exists()
        assert (cache_path / "raw.md").read_text() == extracted_text

    def test_put_creates_metadata(self, tmp_path):
        """put() should create raw.meta.json with correct fields."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        final_url = "https://example.com/article?ref=redirect"
        result = FakeFetchResult(
            url=url,
            final_url=final_url,
            text="Content",
            content_type="text/html",
            fetched_at="2026-04-18T10:00:00Z",
        )
        cache_path = put(url, result, cfg)
        meta_file = cache_path / "raw.meta.json"
        assert meta_file.exists()
        meta_dict = json.loads(meta_file.read_text())
        assert meta_dict["url"] == url
        assert meta_dict["final_url"] == final_url
        assert meta_dict["content_type"] == "text/html"
        assert meta_dict["fetched_at"] == "2026-04-18T10:00:00Z"

    def test_put_creates_directory(self, tmp_path):
        """put() should create cache directory if it doesn't exist."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        result = FakeFetchResult(
            url=url,
            final_url=url,
            text="Content",
            content_type="text/html",
            fetched_at="2026-04-18T10:00:00Z",
        )
        cache_path = put(url, result, cfg)
        assert cache_path.exists()
        assert cache_path.is_dir()


class TestGetMeta:
    """Test metadata retrieval (R04)."""

    def test_get_meta_round_trip(self, tmp_path):
        """put() then get_meta() should return equal dict."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        result = FakeFetchResult(
            url=url,
            final_url="https://example.com/article?redir=true",
            text="Content",
            content_type="text/html; charset=utf-8",
            fetched_at="2026-04-18T10:00:00Z",
        )
        put(url, result, cfg)
        meta = get_meta(url, cfg)
        assert meta["url"] == url
        assert meta["final_url"] == "https://example.com/article?redir=true"
        assert meta["content_type"] == "text/html; charset=utf-8"
        assert meta["fetched_at"] == "2026-04-18T10:00:00Z"

    def test_get_meta_missing_raises(self, tmp_path):
        """get_meta() on missing entry should raise CacheError."""
        cfg = make_config(tmp_path)
        with pytest.raises(CacheError):
            get_meta("https://example.com/missing", cfg)


class TestGetRaw:
    """Test raw file retrieval (R05)."""

    def test_get_raw_html_round_trip(self, tmp_path):
        """put() then get_raw() should return equal text for HTML."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        raw_text = "<html><body>Article</body></html>"
        result = FakeFetchResult(
            url=url,
            final_url=url,
            text=raw_text,
            content_type="text/html",
            fetched_at="2026-04-18T10:00:00Z",
        )
        put(url, result, cfg)
        retrieved = get_raw(url, cfg)
        assert retrieved == raw_text

    def test_get_raw_txt_round_trip(self, tmp_path):
        """put() then get_raw() should return equal text for TXT."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article.txt"
        raw_text = "Plain text content"
        result = FakeFetchResult(
            url=url,
            final_url=url,
            text=raw_text,
            content_type="text/plain",
            fetched_at="2026-04-18T10:00:00Z",
        )
        put(url, result, cfg)
        retrieved = get_raw(url, cfg)
        assert retrieved == raw_text

    def test_get_raw_missing_raises(self, tmp_path):
        """get_raw() on missing entry should raise CacheError."""
        cfg = make_config(tmp_path)
        with pytest.raises(CacheError):
            get_raw("https://example.com/missing", cfg)


class TestGetMarkdown:
    """Test markdown retrieval (R03b)."""

    def test_get_markdown_round_trip(self, tmp_path):
        """put() then get_markdown() should return extracted text."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        markdown_text = "# Article\n\nExtracted article text."
        result = FakeFetchResult(
            url=url,
            final_url=url,
            text=markdown_text,
            content_type="text/html",
            fetched_at="2026-04-18T10:00:00Z",
        )
        put(url, result, cfg)
        retrieved = get_markdown(url, cfg)
        assert retrieved == markdown_text

    def test_get_markdown_missing_raises(self, tmp_path):
        """get_markdown() on missing entry should raise CacheError."""
        cfg = make_config(tmp_path)
        with pytest.raises(CacheError):
            get_markdown("https://example.com/missing", cfg)


class TestWriteMapping:
    """Test mapping write (R06)."""

    def test_write_mapping_creates_file(self, tmp_path):
        """write_mapping() should create mapping.yaml."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        mapping = {"key1": "value1", "key2": ["item1", "item2"]}
        write_mapping(url, mapping, cfg)
        cache_path = path(url, cfg)
        assert (cache_path / "mapping.yaml").exists()

    def test_write_mapping_creates_directory(self, tmp_path):
        """write_mapping() should create cache dir if missing."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        mapping = {"test": "data"}
        write_mapping(url, mapping, cfg)
        cache_path = path(url, cfg)
        assert cache_path.exists()


class TestReadMapping:
    """Test mapping read (R07)."""

    def test_read_mapping_round_trip(self, tmp_path):
        """write_mapping() then read_mapping() should return equal dict."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        mapping = {"role": "engineer", "projects": ["p1", "p2"], "active": True}
        write_mapping(url, mapping, cfg)
        retrieved = read_mapping(url, cfg)
        assert retrieved == mapping

    def test_read_mapping_missing_returns_none(self, tmp_path):
        """read_mapping() on missing entry should return None."""
        cfg = make_config(tmp_path)
        url = "https://example.com/missing"
        result = read_mapping(url, cfg)
        assert result is None

    def test_read_mapping_empty_yaml_returns_empty_dict(self, tmp_path):
        """read_mapping() on empty YAML should return empty dict."""
        cfg = make_config(tmp_path)
        url = "https://example.com/article"
        cache_path = path(url, cfg)
        cache_path.mkdir(parents=True, exist_ok=True)
        (cache_path / "mapping.yaml").write_text("")
        result = read_mapping(url, cfg)
        assert result == {}
