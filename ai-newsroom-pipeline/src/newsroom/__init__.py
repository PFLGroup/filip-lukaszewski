"""ai-newsroom-pipeline — przykładowe, samodzielne moduły potoku redakcyjnego.

Moduły:
    models       – struktury danych (NewsItem, ScoreResult, Draft)
    ingest       – parsowanie RSS/Atom + deduplikacja (URL i podobieństwo tytułów)
    scoring      – deterministyczny scoring GO / NO_GO / REVIEW
    llm          – interfejs klienta LLM + walidacja odpowiedzi (JSON)
    ai_label     – metadane i podpisy oznaczające treści tworzone z udziałem AI
    wp_publisher – publikacja przez WordPress REST API (Application Passwords)
    pipeline     – złożenie kroków w jeden przebieg
"""

__version__ = "0.1.0"
