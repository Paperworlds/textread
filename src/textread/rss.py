"""RSS feed reader — fetch, parse, deduplicate, and track state."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

from textread.fetch import UA

_STATE_PATH = Path("~/.local/paperworlds/textread/rss-state.yaml")
_DIGESTS_DIR = Path("~/.local/paperworlds/textread/rss-digests")


@dataclass
class RssItem:
    title: str
    url: str
    description: str
    guid: str
    source_feed: str
    label: str


@dataclass
class FeedResult:
    url: str
    label: str
    new_items: list[RssItem]
    items_fetched: int
    last_seen_guid: str | None


def _parse_items(xml: str, feed_url: str, label: str) -> list[RssItem]:
    items = []
    for raw in re.findall(r"<item>(.*?)</item>", xml, re.DOTALL):
        title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]>", raw) or re.search(r"<title>(.*?)</title>", raw)
        link_m = re.search(r"<link>(.*?)</link>", raw) or re.search(r"<guid[^>]*>(.*?)</guid>", raw)
        desc_m = (
            re.search(r"<description><!\[CDATA\[(.*?)\]\]>", raw, re.DOTALL)
            or re.search(r"<description>(.*?)</description>", raw, re.DOTALL)
        )
        guid_m = re.search(r"<guid[^>]*>(.*?)</guid>", raw)

        if not (title_m and link_m):
            continue

        title = title_m.group(1).strip()
        url = _unescape(link_m.group(1).strip())
        desc_raw = desc_m.group(1) if desc_m else ""
        desc = re.sub(r"<[^>]+>", "", desc_raw).strip()[:300]
        guid = guid_m.group(1).strip() if guid_m else url

        items.append(RssItem(title=title, url=url, description=desc, guid=guid,
                             source_feed=feed_url, label=label))
    return items


def _unescape(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&lt;", "<")
             .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))


def is_sponsor(item: RssItem) -> bool:
    return "(sponsor)" in item.title.lower()


def strip_utm(url: str) -> str:
    """Remove UTM and common tracking query params, keep the rest."""
    base, _, query = url.partition("?")
    if not query:
        return url
    kept = [p for p in query.split("&") if not re.match(r"utm_|dub_id|trk=|sc_channel", p)]
    return f"{base}?{'&'.join(kept)}" if kept else base


def _url_key(url: str) -> str:
    """Normalised URL for dedup — strip query entirely."""
    return url.partition("?")[0].rstrip("/")


def fetch_feed(feed_url: str, label: str, last_seen_guid: str | None = None) -> FeedResult:
    """Fetch *feed_url* and return items newer than *last_seen_guid*."""
    resp = httpx.get(feed_url, headers={"User-Agent": UA}, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    all_items = _parse_items(resp.text, feed_url, label)

    new_items: list[RssItem] = []
    for item in all_items:
        if last_seen_guid and item.guid == last_seen_guid:
            break
        new_items.append(item)

    top_guid = all_items[0].guid if all_items else last_seen_guid
    return FeedResult(url=feed_url, label=label, new_items=new_items,
                      items_fetched=len(all_items), last_seen_guid=top_guid)


def dedup(items: list[RssItem]) -> list[RssItem]:
    """Remove cross-feed duplicates, keeping first occurrence."""
    seen: set[str] = set()
    out: list[RssItem] = []
    for item in items:
        key = _url_key(item.url)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state(path: Path = _STATE_PATH) -> dict[str, str]:
    """Return {feed_url: last_seen_guid} mapping."""
    p = path.expanduser()
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def save_state(state: dict[str, str], path: Path = _STATE_PATH) -> None:
    p = path.expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(state, default_flow_style=False))


# ---------------------------------------------------------------------------
# Digest log
# ---------------------------------------------------------------------------

def log_path(date: str, digests_dir: Path = _DIGESTS_DIR) -> Path:
    return digests_dir.expanduser() / f"{date}.yaml"


def write_log(data: dict, date: str, digests_dir: Path = _DIGESTS_DIR) -> Path:
    path = log_path(date, digests_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False))
    return path


def read_log(date: str, digests_dir: Path = _DIGESTS_DIR) -> dict:
    path = log_path(date, digests_dir)
    if not path.exists():
        raise FileNotFoundError(f"No RSS digest log for {date}")
    return yaml.safe_load(path.read_text()) or {}


def update_save_status(date: str, url: str, status: str,
                       digests_dir: Path = _DIGESTS_DIR) -> None:
    """Update status of a single save_to_raindrop entry in the log."""
    data = read_log(date, digests_dir)
    for entry in data.get("save_to_raindrop", []):
        if entry.get("url") == url:
            entry["status"] = status
            break
    write_log(data, date, digests_dir)


# ---------------------------------------------------------------------------
# Newsletter scrapers
# ---------------------------------------------------------------------------

_PW_HOMEPAGE = "https://www.pythonweekly.com"


def fetch_newsletter_python_weekly(
    cookie: str,
    issue_url: str | None = None,
    last_seen_guid: str | None = None,
) -> FeedResult:
    """Scrape a Python Weekly issue and return its links as RssItem list.

    The resolved issue URL is used as the guid for state tracking — if
    last_seen_guid matches the resolved URL, the issue is skipped (already seen).
    Defaults to the latest issue when issue_url is None.
    """
    headers = {"Cookie": cookie, "User-Agent": UA}

    if issue_url is None:
        resp = httpx.get(_PW_HOMEPAGE, headers=headers, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        m = re.search(r'href="(/p/python-weekly-issue-[^"]+)"', resp.text)
        if not m:
            raise ValueError("Could not find latest Python Weekly issue link on homepage")
        issue_url = _PW_HOMEPAGE + m.group(1)

    if last_seen_guid and issue_url == last_seen_guid:
        return FeedResult(url=issue_url, label="python-weekly",
                          new_items=[], items_fetched=0, last_seen_guid=issue_url)

    resp = httpx.get(issue_url, headers=headers, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    html = resp.text

    # Each article: <h6><a class="link" href="URL?utm_source=www.pythonweekly.com...">Title</a></h6>
    # followed shortly by a <p> containing the description
    matches = re.findall(
        r'<h6[^>]*><a\s+class="link"\s+href="(https?://[^"]+utm_source=www\.pythonweekly\.com[^"]*)"[^>]*>'
        r'(.*?)</a></h6>.*?<p[^>]*>(.*?)</p>',
        html, re.DOTALL,
    )

    items = []
    for raw_url, title_html, desc_html in matches:
        title = re.sub(r"<[^>]+>", "", title_html).strip()
        desc = re.sub(r"<[^>]+>", "", desc_html).strip()[:300]
        items.append(RssItem(
            title=title,
            url=raw_url,
            description=desc,
            guid=strip_utm(raw_url),
            source_feed=issue_url,
            label="python-weekly",
        ))

    return FeedResult(
        url=issue_url,
        label="python-weekly",
        new_items=items,
        items_fetched=len(items),
        last_seen_guid=issue_url,
    )
