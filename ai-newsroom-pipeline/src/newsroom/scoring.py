"""Deterministyczny scoring wiadomości: GO / NO_GO / REVIEW + priorytet.

Dlaczego bez LLM w pierwszym kroku: scoring obejmuje każdą pobraną wiadomość
(setki dziennie), więc musi być tani, szybki i powtarzalny. LLM dostaje dopiero
kandydatów, którzy przeszli próg — i może skorygować wynik w wąskim zakresie
(patrz `llm.relevance_adjustment`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .ingest import title_tokens
from .models import Decision, NewsItem, Priority, Reach, ScoreResult


@dataclass(frozen=True)
class ScoringConfig:
    weights: dict[str, float] = field(
        default_factory=lambda: {"freshness": 0.35, "reach": 0.20, "uniqueness": 0.15, "fit": 0.20, "seo": 0.10}
    )
    threshold: int = 65
    topics: frozenset[str] = frozenset()             # słowa kluczowe profilu portalu
    breaking_markers: frozenset[str] = frozenset({"pilne", "breaking", "alert"})
    sensitive_markers: frozenset[str] = frozenset({"oskarzenie", "oskarzony", "zarzuty", "maloletni", "samobojstwo"})
    max_age: timedelta = timedelta(hours=48)


def freshness_points(published_at: datetime | None, now: datetime) -> int:
    if published_at is None:
        return 40
    age = now - published_at
    for limit, points in ((1, 100), (3, 85), (6, 70), (12, 50), (24, 30)):
        if age <= timedelta(hours=limit):
            return points
    return 10


def reach_points(reach: Reach) -> int:
    return {Reach.NATIONAL: 100, Reach.REGIONAL: 70, Reach.LOCAL: 50}.get(reach, 40)


def uniqueness_points(coverage: int) -> int:
    """Im więcej źródeł podało ten sam temat, tym mniejsza szansa na unikalny materiał."""
    return {1: 100, 2: 80, 3: 60}.get(coverage, 40)


def fit_points(item: NewsItem, topics: frozenset[str]) -> int:
    if not topics:
        return 50
    tokens = title_tokens(f"{item.title} {item.summary} {' '.join(item.tags)}")
    hits = len(tokens & topics)
    return min(100, 30 + 25 * hits)


def seo_points(title: str, topics: frozenset[str]) -> int:
    points = 0
    if 30 <= len(title) <= 70:
        points += 50
    if any(ch.isdigit() for ch in title):
        points += 20
    if title_tokens(title) & topics:
        points += 30
    return min(points, 100)


def score_item(
    item: NewsItem, now: datetime | None = None, coverage: int = 1, config: ScoringConfig | None = None
) -> ScoreResult:
    cfg = config or ScoringConfig()
    now = now or datetime.now(timezone.utc)

    components = {
        "freshness": freshness_points(item.published_at, now),
        "reach": reach_points(item.reach),
        "uniqueness": uniqueness_points(coverage),
        "fit": fit_points(item, cfg.topics),
        "seo": seo_points(item.title, cfg.topics),
    }
    total = round(sum(components[k] * w for k, w in cfg.weights.items()))
    reasons: list[str] = []
    tokens = title_tokens(f"{item.title} {item.summary}")

    if tokens & cfg.sensitive_markers:
        decision = Decision.REVIEW
        reasons.append("temat wrażliwy — eskalacja do redaktora")
    elif item.published_at is not None and now - item.published_at > cfg.max_age:
        decision = Decision.NO_GO
        reasons.append("wiadomość starsza niż limit świeżości")
    elif total >= cfg.threshold:
        decision = Decision.GO
    else:
        decision = Decision.NO_GO
        reasons.append(f"wynik {total} poniżej progu {cfg.threshold}")

    if components["freshness"] >= 85 and tokens & cfg.breaking_markers:
        priority = Priority.BREAKING
    elif total >= 80:
        priority = Priority.HOT
    elif item.published_at is None:
        priority = Priority.EVERGREEN
    else:
        priority = Priority.STANDARD

    return ScoreResult(total=total, components=components, decision=decision, priority=priority, reasons=tuple(reasons))
