from unittest.mock import MagicMock

import pytest
import requests

from newsroom.models import Draft
from newsroom.wp_publisher import PublishError, WordPressPublisher, markdown_to_html, slugify

DRAFT = Draft(title="Nowy most na Wiśle otwarty", lead="Lead.", body_markdown="## Szczegóły\nTreść **ważna**.\n- a\n- b", source_url="https://example.org/a")


def response(status: int, payload=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


def publisher(session, **kw):
    return WordPressPublisher("https://wp.example.com/", "bot", "app-pass", session=session, sleep=lambda _s: None, **kw)


def test_slugify_polish():
    assert slugify("Zażółć gęślą jaźń — 2026!") == "zazolc-gesla-jazn-2026"


def test_markdown_to_html_escapes_and_formats():
    out = markdown_to_html("## Nagłówek\nTekst **gruby** <script>x</script>\n- jeden\n- dwa")
    assert out == (
        "<h2>Nagłówek</h2>\n<p>Tekst <strong>gruby</strong> &lt;script&gt;x&lt;/script&gt;</p>\n"
        "<ul><li>jeden</li><li>dwa</li></ul>"
    )


def test_publish_creates_draft_with_auth_and_meta():
    session = MagicMock()
    session.request.side_effect = [response(200, []), response(201, {"id": 42})]
    pub = publisher(session)
    assert pub.publish(DRAFT, meta={"ai_assisted_text": "1"}) == 42

    get_call, post_call = session.request.call_args_list
    assert get_call.args == ("GET", "https://wp.example.com/wp-json/wp/v2/posts")
    assert get_call.kwargs["params"] == {"slug": "nowy-most-na-wisle-otwarty", "status": "any"}
    assert post_call.kwargs["auth"] == ("bot", "app-pass")
    body = post_call.kwargs["json"]
    assert body["status"] == "draft"
    assert body["meta"] == {"ai_assisted_text": "1"}
    assert "Źródło:" in body["content"]


def test_publish_is_idempotent_by_slug():
    session = MagicMock()
    session.request.return_value = response(200, [{"id": 7}])
    assert publisher(session).publish(DRAFT) == 7
    assert session.request.call_count == 1  # brak POST


def test_retries_transient_errors_then_succeeds():
    session = MagicMock()
    session.request.side_effect = [requests.Timeout(), response(503), response(200, []), response(201, {"id": 5})]
    sleeps = []
    pub = WordPressPublisher("https://wp.example.com", "bot", "x", session=session, sleep=sleeps.append)
    assert pub.publish(DRAFT) == 5
    assert sleeps == [1.0, 2.0]


def test_client_error_is_not_retried():
    session = MagicMock()
    session.request.return_value = response(401)
    with pytest.raises(PublishError, match="401"):
        publisher(session).publish(DRAFT)
    assert session.request.call_count == 1


def test_gives_up_after_retries():
    session = MagicMock()
    session.request.return_value = response(500)
    with pytest.raises(PublishError, match="3 próbach"):
        publisher(session).find_by_slug("x")
    assert session.request.call_count == 3


def test_dry_run_sends_nothing():
    session = MagicMock()
    pub = publisher(session, dry_run=True)
    assert pub.publish(DRAFT, status="publish") == 0
    assert pub.sent[0]["status"] == "publish"
    session.request.assert_not_called()


def test_rejects_unknown_status():
    with pytest.raises(ValueError):
        publisher(MagicMock()).build_payload(DRAFT, status="trash")


def test_upload_media_sets_headers_and_alt():
    session = MagicMock()
    session.request.side_effect = [response(201, {"id": 9}), response(200, {"id": 9})]
    media_id = publisher(session).upload_media(b"\xff\xd8", "hero.jpg", alt_text="Most", caption="AI")
    assert media_id == 9
    upload = session.request.call_args_list[0]
    assert upload.kwargs["headers"]["Content-Disposition"] == 'attachment; filename="hero.jpg"'
    assert session.request.call_args_list[1].kwargs["json"] == {"alt_text": "Most", "caption": "AI"}
