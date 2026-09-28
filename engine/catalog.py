"""Plain-language descriptions of collectors and agents, for the workspace UI.

The registry owns ids, names and dependencies; this module owns the words a person
reads about each component. Descriptions state what the code does today (for example,
no browser rendering unless a renderer is configured). A test checks that every
registered collector and agent has an entry.
"""

from __future__ import annotations

# group: where the evidence comes from. services: external services the collector calls.
COLLECTORS: dict[str, dict] = {
    "C1": {"group": "site", "services": [],
           "captures": "Fetches a sample of the site's pages, entry page first, plus robots.txt, sitemaps and "
                       "llms.txt, and checks how the site answers AI crawler user agents."},
    "C2": {"group": "site", "services": [],
           "captures": "Turns each page into a structured model: title, meta tags, headings, passages, links, "
                       "images and structured data, each with a locator that proposed changes can target."},
    "C3": {"group": "site", "services": ["DeepSeek"],
           "captures": "Works out what kind of business the site is and pauses the run for confirmation when "
                       "it isn't sure."},
    "C4": {"group": "site", "services": ["DeepSeek"],
           "captures": "Extracts the facts the site states about the business: names, addresses, phones, "
                       "services, locations, prices and policies, each with its source page."},
    "C11": {"group": "site", "services": ["PageSpeed Insights"],
            "captures": "Measures speed and stability on mobile for up to 5 representative pages, with "
                        "real-visitor data where Google has it."},
    "C5": {"group": "search", "services": ["DeepSeek"],
           "captures": "Builds the searches customers would type, and matches each key page to its target query."},
    "C6": {"group": "search", "services": ["Serper", "SerpAPI"],
           "captures": "Captures dated search results from India for those queries; for the top queries also the "
                       "AI Overview, People Also Ask and featured snippet."},
    "C7": {"group": "search", "services": ["Serper", "DeepSeek"],
           "captures": "Collects the questions customers ask, from autocomplete, People Also Ask and the site "
                       "itself, labelled by source and journey stage."},
    "C8": {"group": "search", "services": ["DeepSeek"],
           "captures": "Identifies the competitors that win those searches and fetches a few of their matching "
                       "pages, respecting their robots.txt."},
    "C9": {"group": "ai", "services": [],
           "captures": "Builds the prompts people put to AI assistants about this kind of business and this brand."},
    "C10": {"group": "ai", "services": ["DeepSeek", "Groq"],
            "captures": "Records how AI answers those prompts: Google's AI Overview, DeepSeek and Groq knowledge "
                        "probes and a simulated AI search, each answer dated and labelled by surface."},
    "C12": {"group": "web", "services": ["Serper", "SerpAPI", "Wikidata"],
            "captures": "Looks for the brand where AI systems learn about businesses: Wikipedia, Wikidata, Google's "
                        "Knowledge Graph and the platforms that matter for its industry."},
}

COLLECTOR_GROUPS = {
    "site": "The client's site",
    "search": "Search results",
    "ai": "AI answers",
    "web": "The wider web",
}

# question: what the agent answers. outcome: what the report gives you. how: its method in one sentence.
# example: an illustrative finding of the kind it reports, shown as an example, never as a result.
AGENTS: dict[str, dict] = {
    "S1": {"question": "Can search engines reach, crawl and index the right pages?",
           "outcome": "A per-URL table of status, redirects, canonical target, indexability and sitemap presence.",
           "how": "Follows each sampled URL's status, redirects and canonical tag, and checks robots rules, noindex tags and sitemap entries.",
           "example": "/offers redirects to /deals, but the sitemap still lists /offers."},
    "S2": {"question": "Is the site fast and stable on mobile?",
           "outcome": "Real-visitor and lab speed metrics for the measured pages, with what slows them down.",
           "how": "Reads Google's real-visitor data and a mobile lab test for up to 5 representative pages, then traces slow loads to images, scripts and layout shifts.",
           "example": "INP is 380 ms on the home page because a chat widget blocks the main thread."},
    "S3": {"question": "Do titles and descriptions describe each page accurately and earn the click?",
           "outcome": "Current versus proposed titles, descriptions and link-preview tags, ready to apply.",
           "how": "Checks every title and description for length, duplicates and missing tags; a model judges whether key pages' text matches the page, and rewrites use only the page's own facts.",
           "example": "The title 'Best Family Holiday Resorts' never names the hotel, so a rewrite that does is proposed."},
    "S4": {"question": "Does each page satisfy the search it targets?",
           "outcome": "Each page's target query, how well the page matches it, and the subtopics it misses.",
           "how": "Matches each key page to its target search, compares it with the pages that rank, and checks headings, depth and the subtopics searchers expect.",
           "example": "The page targets 'hotels near Taj Mahal' but never states the distance to the Taj."},
    "S5": {"question": "Which search themes exist, which page owns each, and where do pages compete?",
           "outcome": "A map of themes to owner pages, with gaps and pages competing for the same search.",
           "how": "Groups the search queries into themes, finds the page that owns each theme, and flags themes with no owner or several competing pages.",
           "example": "Three pages compete for 'Agra resort with pool'; none clearly owns it."},
    "S6": {"question": "Who wins these searches, and with what kind of pages?",
           "outcome": "A dated table of who ranks and who holds each search feature, query by query.",
           "how": "Reads the dated search results for each query: who ranks, which search features appear, and what kind of page wins.",
           "example": "For 'hotels in Agra', booking sites hold the top five results and the map pack."},
    "S7": {"question": "Are important pages well linked, with anchors that name them?",
           "outcome": "Inbound links and click depth per page, with specific links to add.",
           "how": "Builds the link graph of the sampled pages: inbound links, click depth, and anchor text that doesn't name its destination.",
           "example": "The resort page is four clicks from home and linked only with 'click here'."},
    "S8": {"question": "Is the structured data valid, complete and true to the page?",
           "outcome": "The structured data found on each page, what's wrong with it, and corrected JSON-LD.",
           "how": "Parses every JSON-LD block, checks it is valid and complete for its type, and compares it with the facts visible on the page.",
           "example": "The page's Hotel schema carries another property's address."},
    "S9": {"question": "Are the name, address, phone and locations consistent everywhere?",
           "outcome": "Contact details side by side from the footer, contact page, structured data and maps.",
           "how": "Lines up the name, address and phone from the footer, contact page, structured data and the Maps listing, and flags mismatches.",
           "example": "The footer phone and the schema phone differ by one digit."},
    "S10": {"question": "Does the site show who runs it and meet the trust expectations of its industry?",
            "outcome": "A checklist of trust and disclosure items, and where on the site each one appears.",
           "how": "Checks the trust items expected for the business type (who runs it, contact details, policies, prices) and where each one is stated.",
           "example": "The cancellation policy is only in a PDF, not on the booking page."},
    "A1": {"question": "Does the site answer the questions customers actually ask?",
           "outcome": "Each question with its answer status, the best passage found, and draft answers for the gaps.",
           "how": "Takes the questions customers ask, looks for a passage that answers each one, and drafts answers from the site's own facts for the gaps.",
           "example": "'Is parking available?' has no answer on the page; a draft is built from the amenities list."},
    "A2": {"question": "Are existing answers structured so search engines can lift them?",
           "outcome": "Heading and answer-first fixes for key passages, with the proposed structure.",
           "how": "Checks whether key sections use question headings and open with a direct answer that a search engine can quote.",
           "example": "The 'Dining' section opens with a slogan instead of saying what the restaurant serves."},
    "A3": {"question": "Does the site serve every stage of the customer journey?",
           "outcome": "Coverage of each stage, from first search to booking and after, with the missing tools.",
           "how": "Maps pages and tools to each journey stage (discover, compare, book, manage) and checks each stage is reachable from the entry page.",
           "example": "No page helps a guest change or cancel a booking."},
    "A4": {"question": "Which featured snippets and People Also Ask boxes can the site realistically win?",
           "outcome": "Opportunities by query: who holds each feature today and what format wins it.",
           "how": "Reads the featured snippets and People Also Ask boxes for the top queries: who holds them, in what format, and whether the site could compete.",
           "example": "A travel blog holds the snippet for 'best time to visit Agra' with a list the site could answer."},
    "G1": {"question": "Can AI crawlers reach the site and read it without running JavaScript?",
           "outcome": "What each AI crawler is allowed and served, and how much content is in the raw HTML.",
           "how": "Requests the site as each AI crawler, reads the robots.txt rules for them, and measures how much text is in the raw HTML without JavaScript.",
           "example": "GPTBot is blocked by robots.txt, and the room details only appear after JavaScript runs."},
    "G2": {"question": "Do key pages state specific, first-hand facts worth quoting?",
           "outcome": "Distinctive facts versus generic claims on each key page.",
           "how": "Separates specific, first-hand facts (numbers, names, places) from generic claims on key pages, and checks that figures carry a source.",
           "example": "'World-class amenities' appears six times; the room count appears once."},
    "G3": {"question": "How often do AI answers mention the brand compared with competitors?",
           "outcome": "A dated matrix of brand and competitor mentions by prompt and AI surface.",
           "how": "Samples AI answers to category prompts on several surfaces and counts how often the brand and its competitors are named.",
           "example": "The brand is named in 1 of 12 answers to 'best hotels near the Taj Mahal'."},
    "G4": {"question": "Which sources do AI answers cite for these topics?",
           "outcome": "Cited domains by type, labelled real, proxy or recalled from memory.",
           "how": "Collects the URLs that AI answers cite, groups their domains by type, and labels each citation real, proxy or recalled from memory.",
           "example": "AI Overviews cite two booking sites and a blog, but not the hotel's own page."},
    "G5": {"question": "Is what AI says about the brand correct and current?",
           "outcome": "Each fact the site states beside what AI answers said about it.",
           "how": "Compares each fact AI answers state about the brand with what the site states, and asks for a second opinion before calling a claim wrong.",
           "example": "An AI answer says the hotel has 50 rooms; the site says 36."},
    "G6": {"question": "Is the brand present and consistent on the sources AI systems rely on?",
           "outcome": "Presence and consistency on Wikipedia, Wikidata, the Knowledge Graph and industry platforms.",
           "how": "Looks for the brand on Wikipedia, Wikidata, Google's Knowledge Graph and industry platforms, and checks the details there match the site.",
           "example": "The Google Maps listing still shows an old phone number."},
}
