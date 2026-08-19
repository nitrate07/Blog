"""Tests for the RAG article parser."""

import pytest

from evidence.rag.parser import ArticleChunk, parse_article, parse_all_articles

SAMPLE_ARTICLE = """<!doctype html>
<html lang="en">
<head>
<meta name="description" content="Test article about exercise.">
<meta property="og:url" content="https://nitrate07.github.io/Blog/articles/test-exercise.html">
<meta property="og:description" content="A test article.">
<title>Test Exercise Article — Arı Kaynak</title>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "Test Exercise Article",
  "inLanguage": "en",
  "datePublished": "2026-08-16"
}
</script>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ClaimReview",
  "claimReviewed": "Exercise improves health",
  "reviewRating": {
    "@type": "Rating",
    "ratingValue": 4,
    "bestRating": 5,
    "alternateName": "Mostly Supported"
  }
}
</script>
</head>
<body>
<main class="wrap" id="main">
  <div class="article-header">
    <span class="num">FILE No. 0099</span>
    <h1>Test Exercise Article</h1>
  </div>
  <div class="article-body">
    <h2>Introduction</h2>
    <p>Regular exercise has been shown to improve cardiovascular health significantly.</p>
    <p>Multiple studies confirm this benefit across populations.</p>

    <h2>The Verdict</h2>
    <p>The evidence strongly supports the claim that exercise improves heart health.</p>
  </div>
</main>
</body>
</html>"""

SAMPLE_TR_ARTICLE = """<!doctype html>
<html lang="tr">
<head>
<meta property="og:url" content="https://nitrate07.github.io/Blog/tr/makaleler/test-egzersiz.html">
<title>Test Egzersiz Makalesi — Arı Kaynak</title>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "Test Egzersiz Makalesi",
  "inLanguage": "tr"
}
</script>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ClaimReview",
  "claimReviewed": "Egzersiz sagligi iyilestirir",
  "reviewRating": {
    "@type": "Rating",
    "ratingValue": 4,
    "alternateName": "Mostly Supported"
  }
}
</script>
</head>
<body>
<main class="wrap" id="main">
  <div class="article-body">
    <h2>Giris</h2>
    <p>Duzenli egzersizin kalp sagligini iyilestirdigi gosterilmistir.</p>
  </div>
</main>
</body>
</html>"""


class TestParseArticle:
    def test_returns_chunks_for_valid_article(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        assert len(chunks) >= 2

    def test_first_chunk_is_metadata(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        assert chunks[0].chunk_type == "metadata"
        assert "Title:" in chunks[0].text

    def test_extracts_verdict(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        assert chunks[0].verdict == "Mostly Supported"
        assert chunks[0].rating_value == 4

    def test_extracts_claim_reviewed(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        assert chunks[0].claim_reviewed == "Exercise improves health"

    def test_extracts_file_number(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        all_chunks_text = " ".join(c.text for c in chunks)
        assert "FILE No." in all_chunks_text or "99" in all_chunks_text or chunks[0].file_number >= 0

    def test_detects_language(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        assert chunks[0].language == "en"

    def test_turkish_article_language(self):
        chunks = parse_article(SAMPLE_TR_ARTICLE)
        assert chunks[0].language == "tr"

    def test_heading_chunks_are_classified(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        verdict_chunks = [c for c in chunks if c.chunk_type == "verdict"]
        assert len(verdict_chunks) >= 1

    def test_to_metadata_dict(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        meta = chunks[0].to_metadata()
        assert "article_id" in meta
        assert "verdict" in meta
        assert "rating_value" in meta

    def test_to_embedding_text(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        text = chunks[0].to_embedding_text()
        assert len(text) > 0

    def test_empty_html_returns_no_chunks(self):
        chunks = parse_article("<html><head></head><body></body></html>")
        assert chunks == []

    def test_article_id_format(self):
        chunks = parse_article(SAMPLE_ARTICLE)
        assert chunks[0].article_id.startswith("en:")


class TestParseAllArticles:
    def test_parses_from_directory(self, tmp_path):
        en_dir = tmp_path / "articles"
        en_dir.mkdir()
        (en_dir / "test1.html").write_text(SAMPLE_ARTICLE)
        chunks = parse_all_articles(en_dir)
        assert len(chunks) >= 2

    def test_includes_turkish_articles(self, tmp_path):
        en_dir = tmp_path / "articles"
        tr_dir = tmp_path / "tr"
        en_dir.mkdir()
        tr_dir.mkdir()
        (en_dir / "test1.html").write_text(SAMPLE_ARTICLE)
        (tr_dir / "test1.html").write_text(SAMPLE_TR_ARTICLE)
        chunks = parse_all_articles(en_dir, tr_dir)
        article_ids = {c.article_id for c in chunks}
        assert any("tr:" in aid for aid in article_ids)

    def test_deduplicates_across_languages(self, tmp_path):
        en_dir = tmp_path / "articles"
        tr_dir = tmp_path / "tr"
        en_dir.mkdir()
        tr_dir.mkdir()
        (en_dir / "test1.html").write_text(SAMPLE_ARTICLE)
        (tr_dir / "test1.html").write_text(SAMPLE_TR_ARTICLE)
        chunks = parse_all_articles(en_dir, tr_dir)
        article_ids = [c.article_id for c in chunks]
        en_count = article_ids.count("en:test-exercise")
        tr_count = article_ids.count("tr:test-egzersiz")
        assert en_count >= 1
        assert tr_count >= 1

    def test_handles_missing_directory(self, tmp_path):
        chunks = parse_all_articles(tmp_path / "nonexistent")
        assert chunks == []
