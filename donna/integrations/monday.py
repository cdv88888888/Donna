"""Monday.com integration — read boards so Donna can track them as projects.

Uses the Monday GraphQL API (v2) with a personal API token. Kept dependency-free
(urllib) so no new packages. Reads each configured board's items, their group,
and their status/date columns, so the projects skill can turn a board into a
live project card (how many items need you, anything overdue).
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from ..config import settings

_ENDPOINT = "https://api.monday.com/v2"


@dataclass
class MondayItem:
    id: str
    name: str
    group: str
    status: str = ""
    date: str = ""


@dataclass
class MondayBoard:
    id: str
    name: str
    items: list[MondayItem] = field(default_factory=list)


def _query(query: str) -> dict:
    req = urllib.request.Request(
        _ENDPOINT,
        data=json.dumps({"query": query}).encode(),
        headers={
            "Authorization": settings.monday_api_token,
            "Content-Type": "application/json",
            "API-Version": "2024-01",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if "errors" in payload:
        raise RuntimeError(f"Monday API error: {payload['errors']}")
    return payload.get("data", {})


def fetch_boards(board_ids: Optional[list[str]] = None) -> list[MondayBoard]:
    ids = board_ids or settings.monday_boards
    if not (settings.monday_api_token and ids):
        return []
    id_list = ", ".join(ids)
    q = f"""
    query {{
      boards(ids: [{id_list}]) {{
        id name
        items_page(limit: 200) {{
          items {{
            id name
            group {{ title }}
            column_values {{ id type text }}
          }}
        }}
      }}
    }}"""
    data = _query(q)
    boards: list[MondayBoard] = []
    for b in data.get("boards", []):
        items = []
        for it in b.get("items_page", {}).get("items", []):
            status = date = ""
            for cv in it.get("column_values", []):
                if cv.get("type") in ("status", "color") and cv.get("text"):
                    status = cv["text"]
                if cv.get("type") in ("date", "timeline") and cv.get("text"):
                    date = cv["text"]
            items.append(MondayItem(
                id=it["id"], name=it["name"],
                group=(it.get("group") or {}).get("title", ""),
                status=status, date=date,
            ))
        boards.append(MondayBoard(id=str(b["id"]), name=b["name"], items=items))
    return boards
