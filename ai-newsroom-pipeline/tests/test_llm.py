import json

import pytest

from newsroom.llm import DraftError, FakeLLMClient, draft_article, extract_json, relevance_adjustment
from newsroom.models import NewsItem

ITEM = NewsItem(source_id="s", title="Rada miasta przyjęła budżet", url="https://example.org/b", summary="Lead.")
BODY = "## Co ustalono\n" + "Radni przyjęli budżet. " * 30


def test_extract_json_handles_code_fences_and_noise():
    raw = 'Oto wynik:\n```json\n{"adjust": 4, "reason": "lokalny temat"}\n```'
    assert extract_json(raw) == {"adjust": 4, "reason": "lokalny temat"}


def test_extract_json_rejects_garbage():
    with pytest.raises(DraftError):
        extract_json("nie wiem")


def test_relevance_adjustment_is_clamped():
    client = FakeLLMClient(responses=['{"adjust": 55, "reason": "bardzo ważne"}'])
    assert relevance_adjustment(client, ITEM) == (10, "bardzo ważne")
    system, prompt = client.calls[0]
    assert "JSON" in system and ITEM.title in prompt


def test_relevance_adjustment_falls_back_to_zero_on_failure():
    def boom(_s, _p):
        raise ConnectionError("provider down")

    assert relevance_adjustment(FakeLLMClient(handler=boom), ITEM)[0] == 0
    assert relevance_adjustment(FakeLLMClient(responses=["???"]), ITEM)[0] == 0


def test_draft_article_valid():
    payload = {"title": "Budżet miasta na 2027 przyjęty", "lead": "Radni zdecydowali.", "body_markdown": BODY, "tags": ["budżet", " "]}
    draft = draft_article(FakeLLMClient(responses=[json.dumps(payload)]), ITEM)
    assert draft.title == payload["title"]
    assert draft.tags == ["budżet"]
    assert draft.source_url == ITEM.url


@pytest.mark.parametrize(
    "patch,message",
    [
        ({"title": ""}, "tytuł"),
        ({"lead": ""}, "leadu"),
        ({"body_markdown": "za krótko"}, "za krótka"),
        ({"tags": "budżet"}, "tags"),
    ],
)
def test_draft_article_rejects_invalid_output(patch, message):
    payload = {"title": "Tytuł", "lead": "Lead", "body_markdown": BODY, "tags": []} | patch
    with pytest.raises(DraftError, match=message):
        draft_article(FakeLLMClient(responses=[json.dumps(payload)]), ITEM)
