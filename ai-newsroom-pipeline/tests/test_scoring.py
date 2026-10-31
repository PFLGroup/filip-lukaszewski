from datetime import timedelta

import pytest

from newsroom.models import Decision, NewsItem, Priority, Reach
from newsroom.scoring import ScoringConfig, freshness_points, score_item, seo_points, uniqueness_points

CFG = ScoringConfig(topics=frozenset({"transport", "budzet", "energia", "most"}))


def make(now, title="Nowy most na Wiśle otwarty dla ruchu po 3 latach", hours=0.5, reach=Reach.NATIONAL, summary=""):
    return NewsItem(
        source_id="s",
        title=title,
        url="https://example.org/a",
        summary=summary,
        published_at=None if hours is None else now - timedelta(hours=hours),
        reach=reach,
        tags=("transport",),
    )


@pytest.mark.parametrize("hours,points", [(0.5, 100), (2, 85), (5, 70), (10, 50), (20, 30), (30, 10)])
def test_freshness_buckets(now, hours, points):
    assert freshness_points(now - timedelta(hours=hours), now) == points


def test_freshness_unknown_date(now):
    assert freshness_points(None, now) == 40


def test_uniqueness_decreases_with_coverage():
    assert [uniqueness_points(n) for n in (1, 2, 3, 7)] == [100, 80, 60, 40]


def test_seo_points_title_length_number_keyword():
    assert seo_points("Nowy most na Wiśle otwarty dla ruchu po 3 latach", frozenset({"most"})) == 100
    assert seo_points("Krótko", frozenset()) == 0


def test_fresh_national_on_topic_item_is_go(now):
    result = score_item(make(now), now=now, config=CFG)
    assert result.decision is Decision.GO
    assert result.total >= CFG.threshold
    assert set(result.components) == {"freshness", "reach", "uniqueness", "fit", "seo"}


def test_score_is_deterministic(now):
    item = make(now)
    assert score_item(item, now=now, config=CFG) == score_item(item, now=now, config=CFG)


def test_weak_item_is_no_go(now):
    item = make(now, title="Krótko", hours=20, reach=Reach.LOCAL)
    result = score_item(item, now=now, coverage=5, config=CFG)
    assert result.decision is Decision.NO_GO
    assert "poniżej progu" in result.reasons[0]


def test_too_old_item_is_no_go_regardless_of_score(now):
    assert score_item(make(now, hours=72), now=now, config=CFG).decision is Decision.NO_GO


def test_sensitive_topic_escalates_to_human(now):
    item = make(now, summary="Prokuratura przedstawiła zarzuty radnemu.")
    result = score_item(item, now=now, config=CFG)
    assert result.decision is Decision.REVIEW


def test_breaking_priority(now):
    item = make(now, title="PILNE: awaria trakcji, transport w centrum wstrzymany", hours=0.2)
    assert score_item(item, now=now, config=CFG).priority is Priority.BREAKING


def test_evergreen_when_no_date(now):
    assert score_item(make(now, hours=None), now=now, config=CFG).priority is Priority.EVERGREEN
