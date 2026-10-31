from datetime import datetime, timezone

from newsroom.ai_label import IMAGE_CAPTION, TEXT_NOTE, AiDisclosure, append_text_note, image_caption

REVIEWED = datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)


def test_meta_roundtrip():
    d = AiDisclosure(image_ai=True, text_ai_assisted=True, reviewed_at=REVIEWED)
    meta = d.to_wp_meta()
    assert meta == {"ai_generated_image": "1", "ai_assisted_text": "1", "editorial_review_at": REVIEWED.isoformat()}
    assert AiDisclosure.from_wp_meta(meta) == d


def test_missing_meta_means_no_label():
    d = AiDisclosure.from_wp_meta({})
    assert not d.image_ai and not d.text_ai_assisted and not d.needs_text_note


def test_image_caption_is_idempotent():
    d = AiDisclosure(image_ai=True, text_ai_assisted=False)
    once = image_caption("Ilustracja do tekstu.", d)
    assert once == f"Ilustracja do tekstu. {IMAGE_CAPTION}"
    assert image_caption(once, d) == once


def test_no_caption_for_non_ai_photo():
    assert image_caption("Fot. agencja", AiDisclosure(image_ai=False, text_ai_assisted=True)) == "Fot. agencja"


def test_text_note_only_without_editorial_review():
    unreviewed = AiDisclosure(image_ai=False, text_ai_assisted=True)
    reviewed = AiDisclosure(image_ai=False, text_ai_assisted=True, reviewed_at=REVIEWED)
    html = "<p>Treść.</p>"
    with_note = append_text_note(html, unreviewed)
    assert TEXT_NOTE in with_note
    assert append_text_note(with_note, unreviewed) == with_note  # bez dublowania
    assert append_text_note(html, reviewed) == html
