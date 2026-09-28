from engine.collectors.c01_crawler import choose_sample

SITE = "https://www.example.com"


def test_deep_entry_page_prioritises_its_section_then_links_then_rest():
    entry = f"{SITE}/resorts-hotels/regalia-agra"
    candidates = [
        f"{SITE}/blog/post-1", f"{SITE}/resorts-hotels/goa", f"{SITE}/resorts-hotels/regalia-agra/rooms",
        f"{SITE}/offers", f"{SITE}/resorts-hotels/regalia-agra/dining", f"{SITE}/blog/post-2",
    ]
    sample = choose_sample(entry, candidates, 6, entry_links=[f"{SITE}/offers"], site_home=f"{SITE}/")
    assert sample[:2] == [entry, f"{SITE}/"]
    assert set(sample[2:4]) == {f"{SITE}/resorts-hotels/regalia-agra/rooms",
                                f"{SITE}/resorts-hotels/regalia-agra/dining"}
    assert sample[4] == f"{SITE}/offers"
    assert len(sample) == 6


def test_root_entry_interleaves_templates_before_repeats():
    candidates = [f"{SITE}/blog/a", f"{SITE}/blog/b", f"{SITE}/loans/x", f"{SITE}/about"]
    sample = choose_sample(f"{SITE}/", candidates, 4, site_home=f"{SITE}/")
    assert sample[0] == f"{SITE}/" and sample.count(f"{SITE}/") == 1
    assert {f"{SITE}/blog/a", f"{SITE}/loans/x", f"{SITE}/about"} <= set(sample)
