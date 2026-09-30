"""RSS feed reader — fetch, parse, deduplicate, and track state."""
from __future__ import annotations

import re
from html import unescape
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
import yaml

from textread.fetch import UA

_STATE_PATH = Path("~/.local/paperworlds/textread/rss-state.yaml")
_DIGESTS_DIR = Path("~/.local/paperworlds/textread/rss-digests")
_SEEN_PATH = Path("~/.local/paperworlds/textread/rss-seen.yaml")
# How long an item stays in the seen ledger before it is pruned.
_SEEN_RETENTION_DAYS = 90


@dataclass
class RssItem:
    title: str
    url: str
    description: str
    guid: str
    source_feed: str
    label: str
    published: str | None = None   # ISO date (YYYY-MM-DD), when the feed says


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
        date_m = re.search(r"<pubDate>(.*?)</pubDate>", raw)

        if not (title_m and link_m):
            continue

        title = title_m.group(1).strip()
        url = _unescape(link_m.group(1).strip())
        desc_raw = desc_m.group(1) if desc_m else ""
        desc = re.sub(r"<[^>]+>", "", desc_raw).strip()[:300]
        guid = guid_m.group(1).strip() if guid_m else url

        items.append(RssItem(title=title, url=url, description=desc, guid=guid,
                             source_feed=feed_url, label=label,
                             published=_parse_pubdate(date_m.group(1) if date_m else None)))
    return items


def _parse_pubdate(raw: str | None) -> str | None:
    """RFC-822 pubDate to an ISO date, or None when absent or unparseable."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw.strip()).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


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


_TRACKING_PARAM = re.compile(r"^(utm_|dub_id|_bhlid|trk|sc_channel|ref|fbclid|gclid|mc_cid|mc_eid)")


def canonical_url(url: str) -> str:
    """One canonical identity for an item, used by state, dedup and the seen ledger.

    Lowercases the host, drops the fragment and every tracking parameter, keeps
    meaningful query params (an id, a page), and trims a trailing slash. Feeds
    hand out the same article under many decorations; this is what makes two of
    them compare equal.
    """
    url = _unescape(_unescape(url)).strip()
    url = url.partition("#")[0]
    base, _, query = url.partition("?")
    m = re.match(r"(?i)^(https?://)([^/]+)(.*)$", base)
    if m:
        base = m.group(1).lower() + m.group(2).lower() + m.group(3)
    kept = [p for p in query.split("&") if p and not _TRACKING_PARAM.match(p)]
    base = base.rstrip("/")
    return f"{base}?{'&'.join(sorted(kept))}" if kept else base


# A title must carry this many words before it is trusted as an identity.
# Short titles ("Projects", "Weekly roundup") collide between genuinely
# different articles; collapsing on those loses items silently.
_TITLE_DEDUP_MIN_WORDS = 5


def title_key(title: str) -> str:
    """Normalised title, for catching one article published under two URLs.

    Returns "" for a title too short to identify an article on its own, which
    disables title matching for that item rather than risking a false collapse.
    """
    norm = re.sub(r"[^a-z0-9]+", " ", _unescape(title).lower()).strip()
    return norm if len(norm.split()) >= _TITLE_DEDUP_MIN_WORDS else ""


def _url_key(url: str) -> str:
    """Deprecated alias kept for callers outside the digest path."""
    return canonical_url(url)


# How many recent item keys to remember per feed. Comfortably more than a
# feed's window, so the cutoff survives items rotating out.
_SEEN_GUID_WINDOW = 400


def fetch_feed(feed_url: str, label: str, seen: list[str] | None = None,
               since: str | None = None) -> FeedResult:
    """Fetch *feed_url* and return the items not already in *seen*.

    *seen* is a rolling list of canonical keys for items this feed has already
    yielded. Filtering against a set, rather than stopping at a single sentinel
    guid, is what makes this robust: the previous implementation remembered only
    the feed's topmost item, which in practice is a rotating sponsor ad, and once
    that ad dropped out of the window nothing matched and the whole feed came
    back as new.
    """
    resp = httpx.get(feed_url, headers={"User-Agent": UA}, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    all_items = _parse_items(resp.text, feed_url, label)

    seen_set = set(seen or [])
    new_items = [i for i in all_items if canonical_url(i.url) not in seen_set]

    if since is not None:
        # Only items the feed dates on or after `since`. Undated items are held
        # back rather than guessed at, so they surface in a later unbounded run.
        new_items = [i for i in new_items if i.published and i.published >= since]

    # The window absorbs only what this run emits. Anything held back by `since`
    # stays unseen, so a narrow run leaves the older gap intact for a later one.
    updated = [canonical_url(i.url) for i in new_items]
    for key in seen or []:
        if key not in set(updated):
            updated.append(key)

    return FeedResult(url=feed_url, label=label, new_items=new_items,
                      items_fetched=len(all_items),
                      last_seen_guid=updated[:_SEEN_GUID_WINDOW])


def dedup(items: list[RssItem]) -> list[RssItem]:
    """Remove cross-feed duplicates within one run, keeping first occurrence.

    Two passes: the same article under decorated URLs (canonical_url), then the
    same article genuinely published at two addresses, caught by an exact match
    on the normalised title.
    """
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    out: list[RssItem] = []
    for item in items:
        url_k = canonical_url(item.url)
        title_k = title_key(item.title)
        if url_k in seen_urls or (title_k and title_k in seen_titles):
            continue
        seen_urls.add(url_k)
        seen_titles.add(title_k)
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state(path: Path = _STATE_PATH) -> dict[str, list[str]]:
    """Return {feed_url: [recent item keys]}.

    Migrates the old {feed_url: single_guid} schema in place: a lone sentinel
    becomes a one-element window. The first run after migration re-emits that
    feed's backlog once, because one key cannot establish what was already seen;
    the seen ledger absorbs it so nothing reaches the digest twice.
    """
    p = path.expanduser()
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text()) or {}
    out: dict[str, list[str]] = {}
    for feed, val in raw.items():
        if isinstance(val, str):
            out[feed] = [canonical_url(val)]
        elif isinstance(val, list):
            out[feed] = list(val)
    return out


def save_state(state: dict[str, list[str]], path: Path = _STATE_PATH) -> None:
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
            published=(meta.get("published_time") or "")[:10] or None,
        ))

    newest = issues[0][0] if issues else last_seen_guid
    return FeedResult(
        url=archive_url,
        label=label,
        new_items=items,
        items_fetched=len(items),
        last_seen_guid=newest,
    )


# ---------------------------------------------------------------------------
# Seen ledger — what has already been surfaced in a digest
# ---------------------------------------------------------------------------

def load_seen(path: Path = _SEEN_PATH) -> dict[str, str]:
    """Return {canonical_url: first-seen date} for items already digested."""
    p = path.expanduser()
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def save_seen(seen: dict[str, str], path: Path = _SEEN_PATH) -> None:
    p = path.expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(seen, default_flow_style=False, sort_keys=True))


def prune_seen(seen: dict[str, str], today: str,
               retention_days: int = _SEEN_RETENTION_DAYS) -> dict[str, str]:
    """Drop ledger entries older than *retention_days* so it stays bounded."""
    cutoff = (datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=timezone.utc)
              - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    return {url: first for url, first in seen.items() if first >= cutoff}


def record_seen(seen: dict[str, str], urls: list[str], today: str) -> dict[str, str]:
    """Add *urls* to the ledger, keeping the earliest date for each."""
    for url in urls:
        key = canonical_url(url)
        if key and key not in seen:
            seen[key] = today
    return seen


def digest_urls(data: dict) -> list[str]:
    """Every URL a digest surfaced — grouped items, must-opens and saves."""
    urls = [i["url"] for g in data.get("groups") or [] for i in g.get("items", []) if i.get("url")]
    urls += [e["url"] for e in data.get("must_open") or [] if e.get("url")]
    urls += [e["url"] for e in data.get("save_to_raindrop") or [] if e.get("url")]
    return urls


def annotate_seen_before(data: dict, seen: dict[str, str]) -> int:
    """Tag items already surfaced in an earlier digest with seen_before: <date>.

    Returns how many entries were tagged. Items are kept, not dropped, so a story
    that resurfaces is still evaluated — it just says so.
    """
    tagged = 0
    groups = [i for g in data.get("groups") or [] for i in g.get("items", [])]
    for entry in groups + (data.get("must_open") or []) + (data.get("save_to_raindrop") or []):
        url = entry.get("url")
        if not url:
            continue
        first = seen.get(canonical_url(url))
        if first:
            entry["seen_before"] = first
            tagged += 1
    return tagged
