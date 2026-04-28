"""Raindrop.io API client — fetch and drain a named collection."""
from __future__ import annotations

import httpx

_BASE = "https://api.raindrop.io/rest/v1"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def find_collection(token: str, name: str) -> int | None:
    """Return the collection ID whose title matches name (case-insensitive), or None."""
    r = httpx.get(f"{_BASE}/collections", headers=_headers(token), timeout=10)
    r.raise_for_status()
    for col in r.json().get("items", []):
        if col.get("title", "").lower() == name.lower():
            return col["_id"]
    return None


def fetch_items(token: str, collection_id: int) -> list[dict]:
    """Return all raindrops in collection_id, handling pagination."""
    items: list[dict] = []
    page = 0
    while True:
        r = httpx.get(
            f"{_BASE}/raindrops/{collection_id}",
            headers=_headers(token),
            params={"page": page, "perpage": 50},
            timeout=10,
        )
        r.raise_for_status()
        batch = r.json().get("items", [])
        items.extend(batch)
        if len(batch) < 50:
            break
        page += 1
    return items


def move_item(token: str, item_id: int, collection_id: int = -1) -> None:
    """Move a raindrop to another collection (default: Unsorted, id=-1)."""
    r = httpx.put(
        f"{_BASE}/raindrop/{item_id}",
        headers=_headers(token),
        json={"collection": {"$id": collection_id}},
        timeout=10,
    )
    r.raise_for_status()


def delete_item(token: str, item_id: int) -> None:
    """Permanently delete a raindrop by ID."""
    r = httpx.delete(f"{_BASE}/raindrop/{item_id}", headers=_headers(token), timeout=10)
    r.raise_for_status()
