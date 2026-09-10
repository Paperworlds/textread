"""RSS feed reader — fetch, parse, deduplicate, and track state."""
from __future__ import annotations

import re
from html import unescape
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


_CODE_ARCHIVE = "https://codenewsletter.ai/archive"
# How many recent issue pages to pull metadata for on a single run.
_CODE_MAX_ISSUES = 15


def extract_code_issue_slugs(html: str) -> list[str]:
    """Return the unique /p/ issue slugs on The Code's homepage, in document order.

    Document order is not chronological — issues are sorted by their published
    date once their metadata has been fetched.
    """
    seen: list[str] = []
    for m in re.finditer(r'href="(/p/[^"#?]+)"', html):
        slug = m.group(1)
        if slug not in seen:
            seen.append(slug)
    return seen


def parse_code_issue_meta(html: str) -> dict[str, str]:
    """Pull og:title, og:description and article:published_time off an issue page."""
    meta: dict[str, str] = {}
    for prop in ("og:title", "og:description", "article:published_time"):
        m = re.search(
            r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"' % re.escape(prop), html
        ) or re.search(
            r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="%s"' % re.escape(prop), html
        )
        if m:
            meta[prop.split(":")[-1]] = unescape(m.group(1)).strip()
    return meta


def fetch_newsletter_beehiiv_spa(
    archive_url: str = _CODE_ARCHIVE,
    label: str = "code-newsletter",
    last_seen_guid: str | None = None,
    max_issues: int = _CODE_MAX_ISSUES,
) -> FeedResult:
    """Scrape a Beehiiv newsletter archive and return recent issues as RssItem list.

    Used for The Code (codenewsletter.ai). Despite the name, no headless browser
    is needed: the archive is server-rendered enough to yield issue links, and
    each issue page carries og:title, og:description and article:published_time.

    The Code is narrative prose whose inline anchor text is a sentence fragment
    ("promise", "surged"), so an issue — not an individual link — is the unit
    here. Each issue becomes one item carrying its title and subtitle.

    The newest issue URL is the guid used for state tracking; issues published no
    later than last_seen_guid's issue are dropped.
    """
    headers = {"User-Agent": UA}
    origin = re.sub(r"(https?://[^/]+).*", r"\1", archive_url)

    resp = httpx.get(archive_url, headers=headers, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    slugs = extract_code_issue_slugs(resp.text)[:max_issues]

    issues: list[tuple[str, dict[str, str]]] = []
    for slug in slugs:
        issue_url = origin + slug
        try:
            r = httpx.get(issue_url, headers=headers, follow_redirects=True, timeout=15)
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        meta = parse_code_issue_meta(r.text)
        if meta.get("title"):
            issues.append((issue_url, meta))

    # Homepage order is not chronological — sort newest first.
    issues.sort(key=lambda pair: pair[1].get("published_time", ""), reverse=True)

    cutoff = None
    for issue_url, meta in issues:
        if issue_url == last_seen_guid:
            cutoff = meta.get("published_time", "")
            break

    items = []
    for issue_url, meta in issues:
        if cutoff is not None and meta.get("published_time", "") <= cutoff:
            continue
        items.append(RssItem(
            title=meta["title"],
            url=issue_url,
            description=meta.get("description", ""),
            guid=issue_url,
            source_feed=archive_url,
            label=label,
        ))

    newest = issues[0][0] if issues else last_seen_guid
    return FeedResult(
        url=archive_url,
        label=label,
        new_items=items,
        items_fetched=len(items),
        last_seen_guid=newest,
    )
