import asyncio

import httpx
import pytest

from engine.core.net import UnsafeURLError, check_url, safe_fetch
from tests.conftest import fake_resolver


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.1.2.3/", "http://169.254.169.254/latest/meta-data",
    "http://[::1]/", "http://100.64.0.1/", "http://internal.test/", "http://metadata.test/",
    "ftp://example.com/", "file:///etc/passwd", "http://user:pass@example.com/", "http:///nohost",
])
def test_unsafe_urls_are_blocked(url):
    with pytest.raises(UnsafeURLError):
        check_url(url, fake_resolver)


def test_public_url_is_allowed():
    assert check_url("https://example.com/page", fake_resolver) == "https://example.com/page"


def test_redirect_to_internal_host_is_blocked():
    transport = httpx.MockTransport(lambda req: httpx.Response(302, headers={"location": "http://10.0.0.9/admin"}))

    async def go():
        async with httpx.AsyncClient(transport=transport) as client:
            return await safe_fetch(client, "https://example.com/", user_agent="t", resolver=fake_resolver)

    result = asyncio.run(go())
    assert result.status is None
    assert result.error.startswith("blocked")
    assert result.redirects[0]["location"] == "http://10.0.0.9/admin"


def test_response_size_is_capped():
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"x" * 5000))

    async def go():
        async with httpx.AsyncClient(transport=transport) as client:
            return await safe_fetch(client, "https://example.com/", user_agent="t", max_bytes=1000,
                                    resolver=fake_resolver)

    result = asyncio.run(go())
    assert result.truncated and len(result.body) == 1000
