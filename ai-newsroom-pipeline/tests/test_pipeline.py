import json
from datetime import timedelta

from newsroom.ingest import parse_feed
from newsroom.llm import FakeLLMClient
from newsroom.models import NewsItem, Reach
from newsroom.pipeline import run_pipeline
from newsroom.scoring import ScoringConfig
from newsroom.wp_publisher import WordPressPublisher

CFG = ScoringConfig(topics=frozenset({"transport", "budzet", "energia", "most", "wisle"}))


def fake_llm():
    def handler(system: str, prompt: str) -> str:
        if '"adjust"' in system:
            return '{"adjust": 3, "reason": "ok"}'
        title = prompt.split("Tytuł źródła: ")[1].split("\n")[0]
        return json.dumps({"title": title[:100], "lead": "Lead.", "body_markdown": "Treść. " * 100, "tags": ["test"]})

    return FakeLLMClient(handler=handler)


def test_end_to_end_dry_run(rss_xml, atom_xml, now):
    items = parse_feed(rss_xml, "regional", Reach.REGIONAL) + parse_feed(atom_xml, "national", Reach.NATIONAL)
    items.append(
        NewsItem(source_id="x", title="Zarzuty dla urzędnika w sprawie przetargu", url="https://example.org/z",
                 published_at=now - timedelta(minutes=10), reach=Reach.NATIONAL)
    )
    publisher = WordPressPublisher("https://wp.example.com", "bot", "x", dry_run=True)

    report = run_pipeline(items, fake_llm(), publisher, config=CFG, now=now)

    assert report.fetched == 5
    assert report.unique == 4
    assert report.review == ["https://example.org/z"]
    assert report.go == len(report.drafted) == len(publisher.sent)
    assert report.go + report.rejected + len(report.review) == report.unique
    for payload in publisher.sent:
        assert payload["status"] == "draft"
        assert payload["meta"]["ai_assisted_text"] == "1"
        assert "narzędzi AI" in payload["content"]


def test_invalid_llm_output_is_reported_not_published(rss_xml, now):
    items = parse_feed(rss_xml, "regional", Reach.NATIONAL)
    llm = FakeLLMClient(handler=lambda s, p: '{"adjust": 0}' if '"adjust"' in s else '{"title": ""}')
    publisher = WordPressPublisher("https://wp.example.com", "bot", "x", dry_run=True)
    report = run_pipeline(items, llm, publisher, config=CFG, now=now)
    assert report.go > 0
    assert len(report.errors) == report.go
    assert publisher.sent == []
