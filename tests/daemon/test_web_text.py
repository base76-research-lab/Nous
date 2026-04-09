from __future__ import annotations

from nouse.daemon import web_text


class _FakeResponse:
    def __init__(self, text: str, content_type: str = "text/html; charset=utf-8") -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def get(self, _url: str) -> _FakeResponse:
        return self._response


def test_extract_text_from_url_includes_author_and_published(monkeypatch):
    html = """
    <html>
      <head>
        <title>Jag fick inte bryta ihop för Ellens skull</title>
        <meta name="author" content="Staffan Lindberg" />
        <meta property="article:published_time" content="2009-01-22" />
      </head>
      <body>
        <article>
          <p>Ingress om en svår livshändelse.</p>
        </article>
      </body>
    </html>
    """
    response = _FakeResponse(html)
    monkeypatch.setattr(
        web_text.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(response),
    )

    text, meta = web_text.extract_text_from_url("https://example.com/article")

    assert meta["source"] == "web_article"
    assert meta["title"] == "Jag fick inte bryta ihop för Ellens skull"
    assert meta["author"] == "Staffan Lindberg"
    assert meta["published_at"] == "2009-01-22"
    assert "Author: Staffan Lindberg" in text
    assert "Published: 2009-01-22" in text
    assert "Ingress om en svår livshändelse." in text


def test_extract_text_from_url_uses_jsonld_author_fallback(monkeypatch):
    html = """
    <html>
      <head>
        <title>Rubrik från title</title>
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "JSON-LD rubrik",
            "author": {"@type": "Person", "name": "Staffan Lindberg"},
            "datePublished": "2009-01-22T00:00:00Z"
          }
        </script>
      </head>
      <body>
        <p>Textmassa.</p>
      </body>
    </html>
    """
    response = _FakeResponse(html)
    monkeypatch.setattr(
        web_text.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(response),
    )

    text, meta = web_text.extract_text_from_url("https://example.com/news")

    assert meta["author"] == "Staffan Lindberg"
    assert meta["published_at"] == "2009-01-22T00:00:00Z"
    assert "Author: Staffan Lindberg" in text
    assert "Published: 2009-01-22T00:00:00Z" in text
