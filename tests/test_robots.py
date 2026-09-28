from engine.lib.robots import parse_robots

ROBOTS = """
User-agent: *
Disallow: /admin
Allow: /admin/public
Disallow: /*.pdf$

User-agent: GPTBot
User-agent: ClaudeBot
Disallow: /

Sitemap: https://example.com/sitemap.xml
"""


def test_longest_match_and_allow_precedence():
    robots = parse_robots(ROBOTS)
    assert not robots.is_allowed("Googlebot", "https://example.com/admin/x")
    assert robots.is_allowed("Googlebot", "https://example.com/admin/public/page")
    assert robots.is_allowed("Googlebot", "https://example.com/")


def test_wildcards_and_end_anchor():
    robots = parse_robots(ROBOTS)
    assert not robots.is_allowed("Googlebot", "https://example.com/files/report.pdf")
    assert robots.is_allowed("Googlebot", "https://example.com/files/report.pdf?v=2")


def test_specific_agent_group_and_grouped_agents():
    robots = parse_robots(ROBOTS)
    assert not robots.is_allowed("Mozilla/5.0 (compatible; GPTBot/1.1)", "https://example.com/")
    assert not robots.is_allowed("ClaudeBot", "https://example.com/about")
    assert robots.sitemaps == ["https://example.com/sitemap.xml"]


def test_empty_disallow_allows_everything():
    assert parse_robots("User-agent: *\nDisallow:\n").is_allowed("Googlebot", "https://example.com/x")
