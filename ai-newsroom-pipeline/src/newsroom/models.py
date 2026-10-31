from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Reach(str, Enum):
    NATIONAL = "national"
    REGIONAL = "regional"
    LOCAL = "local"


@dataclass(frozen=True)
class NewsItem:
    """Pojedyncza wiadomość pobrana ze źródła (RSS/Atom)."""

    source_id: str
    title: str
    url: str
    summary: str = ""
    published_at: datetime | None = None
    reach: Reach = Reach.REGIONAL
    tags: tuple[str, ...] = ()


class Decision(str, Enum):
    GO = "GO"          # kandydat do opracowania
    NO_GO = "NO_GO"    # odrzucony (za słaby / za stary)
    REVIEW = "REVIEW"  # wymaga decyzji człowieka (temat wrażliwy)


class Priority(str, Enum):
    BREAKING = "breaking"
    HOT = "hot"
    STANDARD = "standard"
    EVERGREEN = "evergreen"


@dataclass(frozen=True)
class ScoreResult:
    total: int
    components: dict[str, int]
    decision: Decision
    priority: Priority
    reasons: tuple[str, ...] = ()


@dataclass
class Draft:
    """Szkic artykułu przygotowany z pomocą LLM, przed publikacją."""

    title: str
    lead: str
    body_markdown: str
    tags: list[str] = field(default_factory=list)
    source_url: str = ""
