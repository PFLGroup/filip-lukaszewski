"""Złożenie kroków w jeden przebieg: dedup -> scoring -> korekta LLM -> szkic -> oznaczenie AI -> WordPress.

W produkcji każdy krok jest osobnym zadaniem harmonogramu (z własną blokadą i
logiem), a stan trzyma baza danych. Tu — dla czytelności — wszystko w pamięci.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .ai_label import AiDisclosure, append_text_note
from .ingest import Deduplicator
from .llm import DraftError, LLMClient, draft_article, relevance_adjustment
from .models import Decision, NewsItem
from .scoring import ScoringConfig, score_item
from .wp_publisher import WordPressPublisher, markdown_to_html


@dataclass
class PipelineReport:
    fetched: int = 0
    unique: int = 0
    go: int = 0
    review: list[str] = field(default_factory=list)
    rejected: int = 0
    drafted: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run_pipeline(
    items: list[NewsItem],
    llm: LLMClient,
    publisher: WordPressPublisher,
    config: ScoringConfig | None = None,
    now: datetime | None = None,
    max_drafts: int = 10,
    status: str = "draft",
) -> PipelineReport:
    cfg = config or ScoringConfig()
    now = now or datetime.now(timezone.utc)
    report = PipelineReport(fetched=len(items))

    dedup = Deduplicator()
    unique = dedup.filter(items)
    report.unique = len(unique)

    candidates: list[tuple[int, NewsItem]] = []
    for item in unique:
        result = score_item(item, now=now, coverage=dedup.coverage.get(item.url, 1), config=cfg)
        if result.decision is Decision.REVIEW:
            report.review.append(item.url)
            continue
        if result.decision is Decision.NO_GO:
            report.rejected += 1
            continue
        adjust, _ = relevance_adjustment(llm, item)
        final = result.total + adjust
        if final < cfg.threshold:
            report.rejected += 1
            continue
        candidates.append((final, item))

    report.go = len(candidates)
    candidates.sort(key=lambda pair: pair[0], reverse=True)

    for _, item in candidates[:max_drafts]:
        try:
            draft = draft_article(llm, item)
        except DraftError as exc:
            report.errors.append(f"{item.url}: {exc}")
            continue
        disclosure = AiDisclosure(image_ai=False, text_ai_assisted=True, reviewed_at=None)
        content = append_text_note(markdown_to_html(draft.body_markdown), disclosure)
        post_id = publisher.publish(draft, status=status, meta=disclosure.to_wp_meta(), content_html=content)
        report.drafted.append(post_id)
    return report
