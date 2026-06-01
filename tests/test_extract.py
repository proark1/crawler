from app.extract import extract, looks_empty

SAMPLE = """
<html><head><title>  Hello World  </title>
<meta name="description" content="A test page">
</head><body>
<article>
<h1>Main heading</h1>
<p>This is a reasonably long paragraph of body content that should be extracted
by trafilatura because it contains enough words to look like real article text
rather than boilerplate navigation chrome or a thin single-page-app shell.</p>
</article>
<a href="/about">About</a>
<a href="https://other.com/x">External</a>
<a href="mailto:a@b.com">Mail</a>
<a href="#frag">Frag</a>
</body></html>
"""


def test_extract_title_and_links():
    ex = extract(SAMPLE, "https://example.com/page/")
    assert ex.title == "Hello World"
    assert "https://example.com/about" in ex.links
    assert "https://other.com/x" in ex.links
    # mailto / fragment-only links are skipped
    assert not any(link.startswith("mailto:") for link in ex.links)
    assert ex.metadata.get("description") == "A test page"


def test_extract_text_and_markdown():
    ex = extract(SAMPLE, "https://example.com/")
    assert ex.text and "long paragraph" in ex.text
    assert ex.markdown is not None


def test_extract_strips_nul_bytes():
    ex = extract(SAMPLE.replace("Main heading", "Main\x00heading"), "https://example.com/")
    assert ex.text is None or "\x00" not in ex.text


def test_looks_empty():
    assert looks_empty(None)
    assert looks_empty("short")
    assert not looks_empty("x" * 300)
