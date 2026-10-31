"""Warstwa LLM: wąski interfejs + twarda walidacja odpowiedzi.

Zasady, które sprawdziły się w produkcji:
* kod domenowy zależy od protokołu `LLMClient`, nie od SDK konkretnego dostawcy —
  dostawcę (API, lokalny model, CLI) wymienia się bez zmian w potoku, a w testach
  podstawia się `FakeLLMClient`;
* model zwraca JSON, a każde pole jest walidowane; śmieci z modelu nie mogą trafić
  dalej (do WordPressa) — zamiast tego leci `DraftError`;
* wpływ LLM na scoring jest ograniczony (clamp) — model koryguje, nie decyduje.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .models import Draft, NewsItem


class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


@dataclass
class FakeLLMClient:
    """Klient testowy: zwraca przygotowane odpowiedzi i zapisuje otrzymane prompty."""

    responses: list[str] = field(default_factory=list)
    handler: Callable[[str, str], str] | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        if self.handler is not None:
            return self.handler(system, prompt)
        if not self.responses:
            raise RuntimeError("FakeLLMClient: brak przygotowanych odpowiedzi")
        return self.responses.pop(0)


class DraftError(ValueError):
    """Odpowiedź modelu nie spełnia kontraktu — szkic nie może iść dalej."""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(raw: str) -> dict:
    """Wyciąga obiekt JSON z odpowiedzi modelu (toleruje ```json ... ``` i tekst wokół)."""
    text = _FENCE_RE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise DraftError("odpowiedź nie zawiera obiektu JSON")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise DraftError(f"niepoprawny JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise DraftError("oczekiwano obiektu JSON")
    return data


RELEVANCE_SYSTEM = (
    "Jesteś wydawcą portalu informacyjnego. Oceń, czy wiadomość warto opracować. "
    'Odpowiedz wyłącznie JSON: {"adjust": <liczba od -10 do 10>, "reason": "<krótko>"}.'
)


def relevance_adjustment(client: LLMClient, item: NewsItem, limit: int = 10) -> tuple[int, str]:
    """Korekta wyniku scoringu przez LLM, przycięta do [-limit, limit].

    Każdy błąd (sieć, zły JSON, zły typ) => korekta 0: awaria modelu nie może
    zablokować potoku ani przepchnąć słabej wiadomości.
    """
    prompt = f"Tytuł: {item.title}\nLead: {item.summary}\nŹródło: {item.source_id}"
    try:
        data = extract_json(client.complete(RELEVANCE_SYSTEM, prompt))
        adjust = int(data.get("adjust", 0))
    except Exception:  # noqa: BLE001
        return 0, "korekta LLM niedostępna"
    return max(-limit, min(limit, adjust)), str(data.get("reason", ""))[:200]


DRAFT_SYSTEM = (
    "Jesteś redaktorem portalu informacyjnego. Na podstawie wiadomości źródłowej napisz "
    "własny tekst (bez kopiowania zdań źródła), rzeczowo, z atrybucją źródła. "
    'Zwróć wyłącznie JSON: {"title": str, "lead": str, "body_markdown": str, "tags": [str]}.'
)


def draft_article(
    client: LLMClient,
    item: NewsItem,
    style_guide: str = "",
    min_body_chars: int = 400,
    max_title_chars: int = 110,
) -> Draft:
    prompt = (
        f"{style_guide}\n\n" if style_guide else ""
    ) + f"Tytuł źródła: {item.title}\nTreść źródła: {item.summary}\nURL źródła: {item.url}"
    data = extract_json(client.complete(DRAFT_SYSTEM, prompt))

    title = str(data.get("title", "")).strip()
    lead = str(data.get("lead", "")).strip()
    body = str(data.get("body_markdown", "")).strip()
    tags = data.get("tags", [])

    if not title or len(title) > max_title_chars:
        raise DraftError("tytuł pusty lub za długi")
    if not lead:
        raise DraftError("brak leadu")
    if len(body) < min_body_chars:
        raise DraftError(f"treść za krótka ({len(body)} < {min_body_chars} znaków)")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise DraftError("tags musi być listą napisów")

    return Draft(
        title=title,
        lead=lead,
        body_markdown=body,
        tags=[t.strip() for t in tags if t.strip()][:8],
        source_url=item.url,
    )
