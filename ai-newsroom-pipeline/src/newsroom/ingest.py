"""Pobieranie i normalizacja wiadomości z kanałów RSS 2.0 / Atom oraz deduplikacja.

Celowo bez zewnętrznych zależności (xml.etree + email.utils), żeby moduł dało się
uruchomić i przetestować w izolacji. Pobieranie HTTP jest wstrzykiwane (`fetch`),
więc testy działają offline.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from .models import NewsItem, Reach

ATOM_NS = "{http://www.w3.org/2005/Atom}"
TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid")
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", value)).strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)  # RFC 822 (RSS)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # ISO 8601 (Atom)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _atom_link(entry: ET.Element) -> str:
    links = entry.findall(f"{ATOM_NS}link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return link.get("href", "")
    return links[0].get("href", "") if links else ""


def parse_feed(xml_text: str, source_id: str, reach: Reach = Reach.REGIONAL) -> list[NewsItem]:
    """Parsuje RSS 2.0 lub Atom do listy NewsItem. Pozycje bez tytułu lub linku są pomijane."""
    root = ET.fromstring(xml_text)
    items: list[NewsItem] = []

    if root.tag == f"{ATOM_NS}feed":
        for entry in root.findall(f"{ATOM_NS}entry"):
            url = _atom_link(entry)
            title = _clean_text(entry.findtext(f"{ATOM_NS}title"))
            if not title or not url:
                continue
            items.append(
                NewsItem(
                    source_id=source_id,
                    title=title,
                    url=normalize_url(url),
                    summary=_clean_text(entry.findtext(f"{ATOM_NS}summary")),
                    published_at=_parse_date(
                        entry.findtext(f"{ATOM_NS}updated") or entry.findtext(f"{ATOM_NS}published")
                    ),
                    reach=reach,
                    tags=tuple(c.get("term", "") for c in entry.findall(f"{ATOM_NS}category") if c.get("term")),
                )
            )
        return items

    for item in root.iter("item"):
        title = _clean_text(item.findtext("title"))
        url = (item.findtext("link") or "").strip()
        if not title or not url:
            continue
        items.append(
            NewsItem(
                source_id=source_id,
                title=title,
                url=normalize_url(url),
                summary=_clean_text(item.findtext("description")),
                published_at=_parse_date(item.findtext("pubDate")),
                reach=reach,
                tags=tuple(_clean_text(c.text) for c in item.findall("category") if c.text),
            )
        )
    return items


def fetch_feed(
    url: str, source_id: str, fetch: Callable[[str], str], reach: Reach = Reach.REGIONAL
) -> list[NewsItem]:
    """Pobiera kanał przez wstrzykniętą funkcję `fetch(url) -> str` i parsuje go.

    Błąd jednego źródła nie może zatrzymać całego przebiegu — zwracamy pustą listę,
    a monitoring źródeł (poza tym repozytorium) liczy kolejne porażki.
    """
    try:
        return parse_feed(fetch(url), source_id, reach)
    except Exception:  # noqa: BLE001 — świadomie: izolacja awarii pojedynczego źródła
        return []


def normalize_url(url: str) -> str:
    """Kanoniczny URL: host małymi literami, bez fragmentu, parametrów śledzących i końcowego '/'."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def title_tokens(title: str) -> frozenset[str]:
    """Tokeny tytułu bez polskich znaków diakrytycznych, interpunkcji i bardzo krótkich słów."""
    text = unicodedata.normalize("NFKD", title.lower()).replace("ł", "l")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    words = re.findall(r"[a-z0-9]+", text)
    return frozenset(w for w in words if len(w) > 2)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class Deduplicator:
    """Odrzuca duplikaty: ten sam URL (po normalizacji) lub bardzo podobny tytuł.

    Ten sam temat podany przez kilka źródeł to częsty przypadek — liczymy go w
    `coverage`, bo liczba źródeł jest sygnałem dla scoringu.
    """

    def __init__(self, threshold: float = 0.6) -> None:
        self.threshold = threshold
        self._urls: set[str] = set()
        self._titles: list[tuple[frozenset[str], str]] = []
        self.coverage: dict[str, int] = {}

    def is_duplicate(self, item: NewsItem) -> bool:
        if normalize_url(item.url) in self._urls:
            return True
        tokens = title_tokens(item.title)
        for seen_tokens, seen_url in self._titles:
            if jaccard(tokens, seen_tokens) >= self.threshold:
                self.coverage[seen_url] = self.coverage.get(seen_url, 1) + 1
                return True
        return False

    def add(self, item: NewsItem) -> None:
        url = normalize_url(item.url)
        self._urls.add(url)
        self._titles.append((title_tokens(item.title), url))
        self.coverage.setdefault(url, 1)

    def filter(self, items: Iterable[NewsItem]) -> list[NewsItem]:
        unique: list[NewsItem] = []
        for item in items:
            if not self.is_duplicate(item):
                self.add(item)
                unique.append(item)
        return unique
