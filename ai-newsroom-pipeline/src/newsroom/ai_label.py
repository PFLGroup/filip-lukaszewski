"""Oznaczanie treści tworzonych z udziałem AI (metadane + podpisy).

Kontekst: art. 50 rozporządzenia (UE) 2024/1689 (AI Act) wprowadza obowiązki
przejrzystości dla treści generowanych przez AI. W projekcie przyjęto zasady:

* grafika wygenerowana przez AI  -> zawsze podpis pod obrazem + flaga w metadanych;
* tekst przygotowany z pomocą AI -> flaga w metadanych zawsze; nota widoczna dla
  czytelnika, gdy tekst NIE przeszedł przeglądu redakcyjnego (art. 50 ust. 4
  przewiduje wyjątek dla treści objętych kontrolą redakcyjną i odpowiedzialnością
  redakcyjną).

Kluczowa decyzja techniczna: oznaczenie jest zapisane na OBIEKCIE (meta posta),
a nie wyliczane z treści. Brak metadanych = brak oznaczenia — łatwo to audytować
jednym zapytaniem do bazy. Brzmienia są w jednym miejscu, żeby kanały dystrybucji
(strona, social media, RSS, push) nie rozjechały się w treści oświadczenia.

To jest przykład implementacji, nie porada prawna.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

IMAGE_CAPTION = "Grafika wygenerowana przez AI."
TEXT_NOTE = "Tekst przygotowano z wykorzystaniem narzędzi AI."

META_IMAGE = "ai_generated_image"
META_TEXT = "ai_assisted_text"
META_REVIEW = "editorial_review_at"


@dataclass(frozen=True)
class AiDisclosure:
    image_ai: bool
    text_ai_assisted: bool
    reviewed_at: datetime | None = None  # moment akceptacji przez redaktora

    @property
    def human_reviewed(self) -> bool:
        return self.reviewed_at is not None

    @property
    def needs_text_note(self) -> bool:
        return self.text_ai_assisted and not self.human_reviewed

    def to_wp_meta(self) -> dict[str, str]:
        """Metadane do zapisania przy poście (WordPress `meta`, zarejestrowane w show_in_rest)."""
        meta = {
            META_IMAGE: "1" if self.image_ai else "0",
            META_TEXT: "1" if self.text_ai_assisted else "0",
        }
        if self.reviewed_at is not None:
            meta[META_REVIEW] = self.reviewed_at.isoformat()
        return meta

    @classmethod
    def from_wp_meta(cls, meta: dict[str, str]) -> AiDisclosure:
        reviewed = meta.get(META_REVIEW)
        return cls(
            image_ai=meta.get(META_IMAGE) == "1",
            text_ai_assisted=meta.get(META_TEXT) == "1",
            reviewed_at=datetime.fromisoformat(reviewed) if reviewed else None,
        )


def image_caption(original_caption: str, disclosure: AiDisclosure) -> str:
    """Podpis grafiki z oznaczeniem AI (idempotentnie — bez dublowania przy ponowieniu)."""
    caption = (original_caption or "").strip()
    if not disclosure.image_ai or IMAGE_CAPTION in caption:
        return caption
    return f"{caption} {IMAGE_CAPTION}".strip()


def append_text_note(html: str, disclosure: AiDisclosure) -> str:
    """Dopisuje notę o AI na końcu treści, jeśli jest wymagana. Idempotentne."""
    if not disclosure.needs_text_note or TEXT_NOTE in html:
        return html
    return f'{html.rstrip()}\n<p class="ai-note"><em>{TEXT_NOTE}</em></p>'
