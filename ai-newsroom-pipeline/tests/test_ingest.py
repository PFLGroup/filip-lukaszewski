from datetime import datetime, timezone

from newsroom.ingest import Deduplicator, fetch_feed, normalize_url, parse_feed, title_tokens
from newsroom.models import NewsItem, Reach


def test_parse_rss_cleans_html_strips_tracking_and_skips_empty(rss_xml):
    items = parse_feed(rss_xml, "regional-1")
    assert len(items) == 2  # pozycja bez tytułu pominięta
    first = items[0]
    assert first.url == "https://news.example.org/most-wisla"
    assert first.summary == "Inwestycja kosztowała 420 mln zł . Most ma cztery pasy ruchu."
    assert first.published_at == datetime(2026, 10, 29, 7, 30, tzinfo=timezone.utc)
    assert first.tags == ("infrastruktura", "transport")
    assert items[1].url == "https://news.example.org/budzet-2027"  # fragment usunięty


def test_parse_atom(atom_xml):
    items = parse_feed(atom_xml, "national-1", Reach.NATIONAL)
    assert [i.url for i in items] == [
        "https://other.example.net/2026/10/most",
        "https://other.example.net/2026/10/energia",
    ]
    assert items[0].reach is Reach.NATIONAL
    assert items[1].published_at == datetime(2026, 10, 29, 7, 0, tzinfo=timezone.utc)


def test_normalize_url_keeps_meaningful_query():
    assert normalize_url("HTTPS://Example.COM/a/?id=7&utm_campaign=x&fbclid=y") == "https://example.com/a?id=7"


def test_title_tokens_ignore_diacritics_and_short_words():
    assert title_tokens("Łódź: nowy żłobek w mieście") == frozenset({"lodz", "nowy", "zlobek", "miescie"})


def test_fetch_feed_isolates_source_failure():
    def broken(_url: str) -> str:
        raise TimeoutError("source down")

    assert fetch_feed("https://down.example", "x", broken) == []


def test_fetch_feed_uses_injected_fetcher(rss_xml):
    assert len(fetch_feed("https://news.example.org/rss", "r", lambda _u: rss_xml)) == 2


def test_dedup_by_url_and_similar_title_counts_coverage(rss_xml, atom_xml):
    items = parse_feed(rss_xml, "regional-1") + parse_feed(atom_xml, "national-1")
    items.append(NewsItem(source_id="dup", title="copy", url="https://news.example.org/budzet-2027/"))
    dedup = Deduplicator()
    unique = dedup.filter(items)
    titles = [i.title for i in unique]
    assert len(unique) == 3
    assert "Ceny energii w listopadzie bez zmian" in titles
    # ten sam temat mostu z dwóch źródeł => coverage 2 dla pierwszego zgłoszenia
    assert dedup.coverage["https://news.example.org/most-wisla"] == 2
