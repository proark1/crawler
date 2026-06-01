import pytest

from app.urls import UnsafeURLError, assert_safe_url, normalize, same_host


def test_normalize_strips_fragment_and_trailing_slash():
    assert normalize("https://Example.com/Path/#section") == "https://example.com/Path"


def test_normalize_sorts_query_and_drops_default_port():
    assert normalize("https://example.com:443/a?b=2&a=1") == "https://example.com/a?a=1&b=2"


def test_normalize_keeps_root_slash():
    assert normalize("http://example.com") == "http://example.com/"


def test_same_host():
    assert same_host("https://a.com/x", "http://a.com/y")
    assert not same_host("https://a.com", "https://b.com")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost.localdomain.../",  # malformed -> resolution fails
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "ftp://example.com/",
        "file:///etc/passwd",
    ],
)
def test_assert_safe_url_blocks_unsafe(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url, block_private=True)


def test_assert_safe_url_allows_public_ip():
    assert_safe_url("http://8.8.8.8/", block_private=True)  # should not raise


def test_assert_safe_url_skips_check_when_disabled():
    assert_safe_url("http://127.0.0.1/", block_private=False)  # should not raise
