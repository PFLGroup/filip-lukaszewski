"""Publikacja w WordPressie przez REST API (`/wp-json/wp/v2`).

* uwierzytelnianie: Application Passwords (HTTP Basic) — bez wtyczek, bez haseł kont;
* domyślnie status `draft` (human-in-the-loop) — publikację włącza świadomie wywołujący;
* idempotencja po slugu: ponowienie po błędzie sieci nie tworzy duplikatu;
* retry z wykładniczym odstępem tylko dla błędów przejściowych (5xx, timeout);
* `dry_run=True` — nic nie wysyła, zwraca payload (przydatne w podglądzie i testach).
"""
from __future__ import annotations

import html
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

from .models import Draft


class PublishError(RuntimeError):
    pass


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text.lower()).replace("ł", "l")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def markdown_to_html(md: str) -> str:
    """Minimalny konwerter: nagłówki ##/###, listy '-', **pogrubienie**, akapity.

    Wystarcza dla kontrolowanego formatu z LLM; treść jest escapowana, więc model
    nie wstrzyknie własnego HTML/JS.
    """
    blocks: list[str] = []
    list_items: list[str] = []

    def inline(text: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))

    def flush_list() -> None:
        if list_items:
            blocks.append("<ul>" + "".join(f"<li>{i}</li>" for i in list_items) + "</ul>")
            list_items.clear()

    for raw in md.strip().split("\n"):
        line = raw.strip()
        if not line:
            flush_list()
            continue
        if line.startswith("- "):
            list_items.append(inline(line[2:]))
            continue
        flush_list()
        if line.startswith("### "):
            blocks.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            blocks.append(f"<h2>{inline(line[3:])}</h2>")
        else:
            blocks.append(f"<p>{inline(line)}</p>")
    flush_list()
    return "\n".join(blocks)


@dataclass
class WordPressPublisher:
    base_url: str
    user: str
    app_password: str
    session: Any = None
    dry_run: bool = False
    retries: int = 3
    backoff_s: float = 1.0
    timeout_s: float = 20.0
    sleep: Callable[[float], None] = time.sleep
    sent: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if self.session is None:
            self.session = requests.Session()

    @property
    def api(self) -> str:
        return f"{self.base_url}/wp-json/wp/v2"

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                resp = self.session.request(
                    method, url, auth=(self.user, self.app_password), timeout=self.timeout_s, **kwargs
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
            else:
                if resp.status_code < 500:
                    if resp.status_code >= 400:
                        raise PublishError(f"{method} {url} -> HTTP {resp.status_code}")
                    return resp.json()
                last_exc = PublishError(f"{method} {url} -> HTTP {resp.status_code}")
            if attempt < self.retries - 1:
                self.sleep(self.backoff_s * 2**attempt)
        raise PublishError(f"nie udało się po {self.retries} próbach: {last_exc}")

    def find_by_slug(self, slug: str) -> int | None:
        found = self._request("GET", f"{self.api}/posts", params={"slug": slug, "status": "any"})
        return int(found[0]["id"]) if found else None

    def build_payload(
        self,
        draft: Draft,
        status: str = "draft",
        categories: list[int] | None = None,
        meta: dict[str, str] | None = None,
        featured_media: int | None = None,
        content_html: str | None = None,
    ) -> dict:
        if status not in {"draft", "pending", "publish", "future"}:
            raise ValueError(f"nieobsługiwany status: {status}")
        body = content_html if content_html is not None else markdown_to_html(draft.body_markdown)
        if draft.source_url:
            body += f'\n<p class="source">Źródło: <a href="{html.escape(draft.source_url)}" rel="nofollow">{html.escape(draft.source_url)}</a></p>'
        payload: dict[str, Any] = {
            "title": draft.title,
            "slug": slugify(draft.title),
            "excerpt": draft.lead,
            "content": body,
            "status": status,
        }
        if categories:
            payload["categories"] = categories
        if meta:
            payload["meta"] = meta
        if featured_media:
            payload["featured_media"] = featured_media
        return payload

    def publish(self, draft: Draft, **kwargs: Any) -> int:
        """Tworzy post (domyślnie szkic). Zwraca ID; jeśli slug istnieje — ID istniejącego."""
        payload = self.build_payload(draft, **kwargs)
        if self.dry_run:
            self.sent.append(payload)
            return 0
        existing = self.find_by_slug(payload["slug"])
        if existing is not None:
            return existing
        created = self._request("POST", f"{self.api}/posts", json=payload)
        self.sent.append(payload)
        return int(created["id"])

    def upload_media(self, data: bytes, filename: str, mime: str = "image/jpeg", alt_text: str = "", caption: str = "") -> int:
        if self.dry_run:
            return 0
        media = self._request(
            "POST",
            f"{self.api}/media",
            data=data,
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "Content-Type": mime},
        )
        media_id = int(media["id"])
        if alt_text or caption:
            self._request("POST", f"{self.api}/media/{media_id}", json={"alt_text": alt_text, "caption": caption})
        return media_id
