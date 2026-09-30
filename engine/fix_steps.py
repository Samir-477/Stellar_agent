"""How to fix each check's issue: concrete steps and who does them (user decision, 2026-09-30).

One reviewed entry per check, written once and never generated: free, identical on every run, and worded
for every kind of business. `{pages}` in a step becomes the issue's own pages ("/a, /b and 2 more"), or
"the affected pages" when the issue is site-wide. The site's own numbers stay in "On your site" and the
technical details, which the steps point to where the exact list lives.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

DEV, CONTENT, MARKETING, OWNER, COMPLIANCE = (
    "Developer", "Content writer", "Marketing team", "Business owner", "Compliance team")


@dataclass(frozen=True)
class Fix:
    owner: str
    steps: tuple[str, ...]


def F(owner: str, *steps: str) -> Fix:
    return Fix(owner, steps)


STEPS: dict[str, Fix] = {
    # ---------------------------------------------------------------- S1 Crawl & index health
    "S1.01": F(DEV, "Open {pages} and note the error each one returns.",
               "If a page moved, forward its old address to the new one with a permanent (301) redirect.",
               "If a page is gone for good, remove or update every link that points to it."),
    "S1.02": F(DEV, "Decide for {pages} whether each page should exist.",
               "For pages that shouldn't exist, make the server return a real 'not found' (404 or 410) status.",
               "For pages that should exist, add their real content."),
    "S1.03": F(DEV, "List the hops for {pages}; the technical details show each chain.",
               "Change every redirect so it points straight at the final address in one hop.",
               "Update menus, internal links and the sitemap to use the final address."),
    "S1.04": F(DEV, "Find the noindex instruction on {pages}, in the robots meta tag or the X-Robots-Tag header.",
               "Remove it from every page you want found in search; keep it only on pages meant to stay private.",
               "Ask Google to recrawl the pages with URL Inspection in Search Console."),
    "S1.05": F(DEV, "Open /robots.txt and find the Disallow rules that match {pages}.",
               "Remove or narrow those rules so search engines can visit the pages you want found.",
               "Test the new file with the robots.txt report in Google Search Console."),
    "S1.06": F(DEV, "Add a canonical tag to {pages} that names each page's own preferred address.",
               "Use the full https address, the same one used in the sitemap and in internal links.",
               "Make sure no canonical points to a redirect or an error page."),
    "S1.07": F(DEV, "Generate an XML sitemap of every page you want in search; most site platforms can do this "
                    "automatically.",
               "Publish it at /sitemap.xml and add a 'Sitemap:' line pointing to it in robots.txt.",
               "Submit it in Google Search Console and fix any errors it reports."),
    "S1.08": F(DEV, "Pick one main form of the address: https, with or without www, and one trailing-slash style.",
               "Forward every other version to it with a permanent (301) redirect at the server or CDN.",
               "Use that main form in canonical tags, internal links and the sitemap."),
    "S1.09": F(CONTENT, "Compare {pages} and decide whether they serve different purposes.",
               "If they do, rewrite each with its own details, questions and examples.",
               "If they don't, keep the stronger page and forward the other to it with a 301 redirect."),
    "S1.10": F(DEV, "Serve every page over https and forward http addresses to https.",
               "Change image, script and style links on {pages} from http:// to https://.",
               "Set the security certificate to renew automatically."),
    "S1.11": F(DEV, "Add the lang attribute to the html tag in the site template, for example lang=\"en-IN\".",
               "Use the code that matches each page's language, such as \"hi\" for Hindi pages.",
               "Check the page source once after publishing."),
    # ---------------------------------------------------------------- S2 Page experience
    "S2.01": F(DEV, "Run PageSpeed Insights on {pages} and note the element it marks as the Largest Contentful "
                    "Paint.",
               "If it is an image: compress it, serve WebP or AVIF, don't lazy-load it, and add "
               "fetchpriority=\"high\".",
               "Defer the scripts and styles that stop the page from showing (render-blocking resources).",
               "Aim for 2.5 seconds or less on mobile."),
    "S2.02": F(DEV, "Open {pages} in PageSpeed Insights or Chrome DevTools and find the long tasks and the "
                    "scripts behind them.",
               "Load chat, ad and tracking scripts after the page is usable (defer or async), and remove the ones "
               "you don't use.",
               "Split long JavaScript tasks so the page answers a tap within 200 ms."),
    "S2.03": F(DEV, "Find the elements that move while {pages} load; PageSpeed Insights lists them.",
               "Give images, videos and ad slots a width and height, or an aspect-ratio.",
               "Reserve space for banners and pop-ups, or show them without pushing content down.",
               "Aim for a layout shift score of 0.1 or less."),
    "S2.04": F(DEV, "Measure the server response time for {pages}, and check whether redirects add to it.",
               "Turn on page caching on the server and serve the site through a CDN.",
               "Remove redirects that run before the page loads.",
               "Aim for a first response in 0.8 seconds or less."),
    "S2.05": F(DEV, "Read which loading step takes longest in the technical details: server wait, finding the "
                    "image, downloading it, or drawing it.",
               "Server wait: add caching or a CDN. Finding the image: put it in the HTML and preload it.",
               "Downloading: compress the image. Drawing: cut render-blocking scripts and styles."),
    "S2.06": F(DEV, "Resize the images on {pages} to the size they are shown at, and serve WebP or AVIF.",
               "Add a width and height to every image so its space is reserved.",
               "Lazy-load images further down the page, but never the main (hero) image."),
    "S2.07": F(DEV, "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"> to the page "
                    "template.",
               "Use body text of at least 16 px on phones.",
               "Make buttons and links at least 48 px tall, with space between them."),
    "S2.08": F(DEV, "List the scripts and styles on {pages} that block the page, with their sizes; the technical "
                    "details show them.",
               "Add defer or async to scripts not needed for the first view, and load third-party widgets after "
               "the page shows.",
               "Remove unused JavaScript and CSS, and split large bundles."),
    # ---------------------------------------------------------------- S3 Search metadata
    "S3.01": F(CONTENT, "Write a title for {pages} that names what each page is about.",
               "Make every title unique across the site: page topic first, brand last.",
               "Set it as the page title (the <title> tag), usually in the site's SEO settings."),
    "S3.02": F(CONTENT, "Rewrite the titles on {pages} to 30 to 60 characters.",
               "Put the main topic words first and the brand last.",
               "Cut filler words and repeated brand names."),
    "S3.03": F(CONTENT, "Review the proposed titles for {pages} in the technical details.",
               "Correct any detail that isn't accurate, then publish them.",
               "Keep each title about its own page's topic, not the whole brand."),
    "S3.04": F(CONTENT, "Compare the title and the main heading (H1) on {pages}.",
               "Rewrite one or both so they describe the same topic, in slightly different words."),
    "S3.05": F(CONTENT, "Write a description of 70 to 155 characters for {pages}.",
               "Say what the page offers and one concrete detail, such as a price, place or feature.",
               "Make each description unique; don't reuse the homepage's."),
    "S3.06": F(CONTENT, "Review the proposed descriptions for {pages} in the technical details.",
               "Check every fact in them against the page, then publish.",
               "Keep them between 70 and 155 characters."),
    "S3.07": F(DEV, "Add og:title, og:description and og:image tags to {pages}.",
               "Use an image of at least 1200 x 630 px that shows the page's subject.",
               "Test a shared link in a sharing debugger, such as Facebook's or LinkedIn's."),
    # ---------------------------------------------------------------- S4 On-page content
    "S4.01": F(CONTENT, "Check that {pages} each have exactly one main heading (H1).",
               "Make that heading name the page's subject in plain words.",
               "Turn extra H1s into H2s, or ask the developer to style them without the H1 tag."),
    "S4.02": F(CONTENT, "Outline the headings on {pages}: one H1, then H2 for sections and H3 inside them.",
               "Fix skipped levels, and stop using headings only for their looks.",
               "Give each section heading words that describe the section."),
    "S4.03": F(CONTENT, "Write a two- or three-sentence opening for {pages} that answers the page's main question.",
               "Include the key facts: what it is, who it's for, where, and the price or next step.",
               "Move slogans and general marketing text below that opening."),
    "S4.04": F(CONTENT, "Look at the pages that rank for the target search; the technical details list them.",
               "If they are a different type of page (a guide, a list, a product page), reshape {pages} to match, "
               "or target a more specific search.",
               "Update the title and main heading to match the search you choose."),
    "S4.05": F(CONTENT, "Take the missing subtopics listed in the technical details.",
               "Add a short section on each to {pages}, with facts you can stand behind.",
               "Use the customers' own words in the section headings."),
    "S4.06": F(CONTENT, "Add what the page offers, key facts (prices, features, eligibility, locations) and common "
                        "questions to {pages}.",
               "Replace repeated template text with text written for that page.",
               "If a page has nothing of its own to say, merge it into a related page."),
    "S4.07": F(CONTENT, "Find expired offers, old prices and past dates on {pages}.",
               "Update or remove them, and add 'valid until' or 'as of' dates to offers and rates.",
               "Review time-sensitive content every month."),
    "S4.08": F(CONTENT, "Split the paragraphs on {pages} to under 120 words, and sentences to under 25 words.",
               "Turn lists of features, steps or documents into bullet lists.",
               "Replace jargon with plain words, or explain it once."),
    "S4.09": F(CONTENT, "Count how often the phrase repeats on {pages}.",
               "Keep it in the title, main heading and opening; use natural variations elsewhere.",
               "Remove keyword lists and repeated phrases in footers or hidden text."),
    # ---------------------------------------------------------------- S5 Keyword themes
    "S5.01": F(CONTENT, "Check whether the site already has a page for each theme in the technical details; it may "
                        "be outside the pages we read.",
               "Where none exists, create a page or a clear section for it.",
               "Link it from the menu or from related pages."),
    "S5.02": F(CONTENT, "For each group of competing pages ({pages}), choose the one page that should rank.",
               "Move the useful content from the others into it and forward them with 301 redirects, or refocus "
               "them on a different topic.",
               "Link the remaining pages to the main one with descriptive link words."),
    "S5.03": F(CONTENT, "Write one sentence saying what {pages} are for: inform, compare, buy or contact.",
               "Remove or move content that serves a different purpose.",
               "Make the title, heading and main button match that purpose."),
    "S5.04": F(CONTENT, "List the places customers add to their searches (cities, areas); the technical details "
                        "show them.",
               "Add a page or section for each place you actually serve, with its address, hours and local "
               "details.",
               "Link them from a locations page."),
    "S5.05": F(MARKETING, "Review the recurring topics in the technical details with your team.",
               "Plan a page or section for each one that fits the business.",
               "Skip topics you don't offer; don't write about them just for search."),
    # ---------------------------------------------------------------- S6 Search results & competitors
    "S6.01": F(MARKETING, "List the searches in the technical details where competitors appear and you don't.",
               "Pick the ones the site can realistically win: specific, local, or about your own offering.",
               "Strengthen the matching page for each: answer the search directly, add facts, and link to it "
               "from other pages."),
    "S6.02": F(MARKETING, "Review the competitor list in the technical details and correct any site that is "
                          "labelled wrongly.",
               "Pick three direct competitors to compare against.",
               "Compare their pages for your main searches with yours."),
    "S6.03": F(MARKETING, "Note the extra boxes Google shows for your searches: questions, maps, images or videos.",
               "Prepare content in that format: a question-and-answer section, a complete Maps listing or good "
               "images.",
               "Put it on the page that targets that search."),
    "S6.04": F(CONTENT, "Review the elements competitors have and you don't; the technical details list them.",
               "Add the ones that fit your business, such as prices, a comparison table, questions and answers, or "
               "reviews.",
               "Mark up prices and reviews as structured data only where they are real and visible."),
    "S6.05": F(CONTENT, "Compare {pages} with the competing pages in the technical details.",
               "Add the useful details they cover and you don't: specifics, examples and answers.",
               "Don't pad the page; length alone doesn't help."),
    # ---------------------------------------------------------------- S7 Internal linking
    "S7.01": F(CONTENT, "Add at least two links to {pages} from related pages.",
               "Add the important ones to the menu or to a hub page.",
               "If a page isn't meant to be found, remove it from the sitemap instead."),
    "S7.02": F(DEV, "Link {pages} from the homepage or the main menu, so they are at most three clicks away.",
               "Add hub pages that group related key pages.",
               "Check that breadcrumbs lead back up the structure."),
    "S7.03": F(CONTENT, "Find sentences on other pages that mention the topics of {pages}.",
               "Turn those mentions into links with descriptive words.",
               "Aim for at least three links in the text to each key page."),
    "S7.04": F(CONTENT, "Replace link words like 'click here' or 'read more' on {pages} with words that name the "
                        "destination.",
               "Give linked images alt text that says where they lead."),
    "S7.05": F(DEV, "List the links on {pages} that pass through a redirect; the technical details show them.",
               "Change each link to the final address.",
               "For menu and footer links, change the site template once."),
    "S7.06": F(CONTENT, "On {pages}, find mentions of related services, products or guides.",
               "Link those mentions to the matching pages."),
    "S7.07": F(CONTENT, "Review the suggested links in the technical details.",
               "Add the ones that help readers, with the suggested link words."),
    # ---------------------------------------------------------------- S8 Structured data
    "S8.01": F(DEV, "Open the structured data (JSON-LD) on {pages} at the place the technical details show.",
               "Fix the syntax error: usually a missing comma, bracket or quote.",
               "Check it with Google's Rich Results Test or the Schema Markup Validator."),
    "S8.02": F(DEV, "Add the missing properties listed in the technical details to the structured data on {pages}.",
               "Use only facts that the page shows.",
               "Check the result with Google's Rich Results Test."),
    "S8.03": F(DEV, "Add the structured data type that matches the business (named in the technical details) to "
                    "{pages}.",
               "Fill in the name, address, phone, website and hours exactly as the page shows them.",
               "Link it to the Organization entry with a shared @id, then validate it."),
    "S8.04": F(DEV, "Compare the structured data on {pages} with what the page shows.",
               "Remove or correct anything the page doesn't show, such as another business's details or template "
               "leftovers.",
               "Validate it after the change."),
    "S8.05": F(DEV, "Leave the existing markup on {pages} as it is; it does no harm.",
               "Don't add more of this type expecting rich results: Google no longer shows them for most sites."),
    "S8.06": F(DEV, "Choose one official name, description, logo and address for the business.",
               "Use them in every structured data block, with one shared @id for the organization.",
               "Link the official profiles with sameAs."),
    "S8.07": F(DEV, "Remove review or rating markup on {pages} that isn't backed by reviews shown on that page.",
               "Don't mark up reviews of your own business on your own site; Google doesn't show stars for them.",
               "Validate it after the change."),
    # ---------------------------------------------------------------- S9 Local presence
    "S9.01": F(MARKETING, "Decide the official business name, address and phone number.",
               "Make the site footer, contact page, structured data and Google Business Profile match them exactly.",
               "Update the main directories and listings the same way."),
    "S9.02": F(CONTENT, "Add the full address with PIN code, the opening hours and the phone number as text on "
                        "{pages}.",
               "Add a map link with directions.",
               "Ask the developer to add LocalBusiness structured data with the same details."),
    "S9.03": F(OWNER, "Claim or verify the Google Business Profile at business.google.com.",
               "Set the main category, hours, phone, website and address, matching the site.",
               "Add photos, and keep the hours current, including holidays."),
    "S9.04": F(OWNER, "Complete the Google Business Profile: categories, services, hours and photos.",
               "Ask satisfied customers for Google reviews, and reply to reviews.",
               "Make sure the site's location page matches the profile and links to it."),
    "S9.05": F(CONTENT, "Show the address with its six-digit PIN code on {pages}.",
               "Show phone numbers with +91, and make them tap-to-call (tel: links)."),
    "S9.06": F(MARKETING, "List the cities and areas you serve as text on the site.",
               "Add the same areas to the Google Business Profile's service areas.",
               "Ask the developer to add them as areaServed in the structured data."),
    # ---------------------------------------------------------------- S10 Trust
    "S10.01": F(OWNER, "Write an about page: who runs the business, since when, what it does and where.",
                "Add credentials: registration numbers, licences, and awards with their source.",
                "Link it from the main menu or the footer."),
    "S10.02": F(CONTENT, "List the phone, email, address and hours as plain text on the contact page.",
                "Make the phone tap-to-call and the email clickable.",
                "Link the contact page from every page's footer."),
    "S10.03": F(CONTENT, "Add the author's name and a short bio to the articles on {pages}.",
                "For financial, health or legal content, also name a qualified reviewer.",
                "Ask the developer to add the author to the Article structured data."),
    "S10.04": F(CONTENT, "Show 'Published' and 'Last updated' dates on {pages}.",
                "Ask the developer to add datePublished and dateModified to the structured data.",
                "Change the update date only when the content really changes."),
    "S10.05": F(OWNER, "Publish each missing policy (privacy, terms, refunds or cancellations) as a plain-text page.",
                "Link them from the footer and from the checkout, booking or application steps."),
    "S10.06": F(COMPLIANCE, "Send the missing disclosures listed in the technical details to your compliance team.",
                "Add each confirmed disclosure where customers decide: next to rates, fees or the application.",
                "This is not legal advice; your compliance team decides the wording."),
    "S10.07": F(CONTENT, "Show each testimonial's reviewer name (or its source) and date on {pages}.",
                "Link to the review site the reviews come from.",
                "Remove testimonials you can't attribute."),
    "S10.08": F(OWNER, "Show full prices on {pages}, including taxes and fees, or a clear 'from' price.",
                "Say what the price includes and any conditions.",
                "Keep prices in the structured data identical to the page."),
    # ---------------------------------------------------------------- A1 Answer coverage
    "A1.01": F(CONTENT, "Review the questions and our draft answers in the technical details.",
               "Correct the drafts with your confirmed facts, and fill in the answers marked as needing facts.",
               "Publish each answer on the most relevant page, under a heading that asks the question."),
    "A1.02": F(CONTENT, "Review the suggested questions and drafts in the technical details.",
               "Answer the ones customers really ask, using confirmed facts.",
               "Place each answer on the page where the question comes up."),
    "A1.03": F(CONTENT, "Compare the answers flagged in the technical details with your confirmed facts.",
               "Correct every page that states the wrong fact.",
               "Update the same fact on listings and profiles."),
    "A1.04": F(CONTENT, "Take the missing topics listed in the technical details.",
               "Add a short, factual section on each to the most relevant page.",
               "Use the customers' own words in the section headings."),
    # ---------------------------------------------------------------- A2 Answer structure
    "A2.01": F(CONTENT, "Review the drafted openings for {pages} in the technical details.",
               "Start each section with a direct answer of 40 to 60 words, with the detail after it.",
               "Check every fact in the drafts before publishing."),
    "A2.02": F(CONTENT, "Pick the key sections on {pages}.",
               "Rephrase their headings as the questions customers ask; the technical details list the questions.",
               "Put the answer right under each heading."),
    "A2.03": F(CONTENT, "Find the paragraphs on {pages} that start with 'it', 'this' or 'they'.",
               "Rewrite them so each names its subject and makes sense on its own."),
    "A2.04": F(CONTENT, "On {pages}, turn steps into numbered lists, features into bullet lists and comparisons into "
                        "tables.",
               "Use real lists and tables, not images or styled paragraphs."),
    "A2.05": F(CONTENT, "Split the answer paragraphs on {pages} into two to four sentences.",
               "Put the direct answer in the first sentence."),
    "A2.06": F(DEV, "Make sure the answer text on {pages} is in the page's HTML, not loaded only when clicked.",
               "Keep the accordions if you like: they may hide the text visually as long as it is in the page.",
               "Check the page source shows the answers."),
    "A2.07": F(DEV, "Find nosnippet, max-snippet or data-nosnippet on {pages}.",
               "Remove them, unless they were added on purpose (for example for legal text)."),
    # ---------------------------------------------------------------- A3 Customer journey
    "A3.01": F(MARKETING, "Look at the weak steps of the customer journey listed in the technical details.",
               "Add a page, section or tool for each, such as rates and eligibility for comparing, or a calculator "
               "or document list for planning.",
               "Link them from the entry page."),
    "A3.02": F(DEV, "Put each key tool (booking, quote, calculator or application form) on the page that needs it, "
                    "in the HTML the server sends.",
               "Test that it works on a phone.",
               "Link to it from the entry page."),
    "A3.03": F(CONTENT, "Add a clear call to action in the content of {pages}: apply, book, enquire or call.",
               "Place it right after the key information, not only in the menu.",
               "Make the button say what happens next."),
    "A3.04": F(MARKETING, "Rank the journey steps by how often customers ask about them; see the technical details.",
               "Cover the most-asked steps first, starting with their questions."),
    # ---------------------------------------------------------------- A4 Snippets & People Also Ask
    "A4.01": F(CONTENT, "For each search in the technical details, see which format Google shows: a paragraph, list "
                        "or table.",
               "Answer it on the matching page in that format, right under a heading with the question.",
               "Keep paragraph answers to 40 to 60 words."),
    "A4.02": F(CONTENT, "Take the People Also Ask questions in the technical details.",
               "Answer each under a question-style heading on the most relevant page.",
               "Put the direct answer in the first sentence."),
    "A4.03": F(CONTENT, "Check which format Google shows for the search; the technical details say which.",
               "Rewrite the answer on {pages} in that format: a short paragraph, a list or a table."),
    # ---------------------------------------------------------------- G1 AI access
    "G1.01": F(DEV, "Open /robots.txt and find rules that block AI search tools such as OAI-SearchBot, ChatGPT-User, "
                    "Claude-SearchBot or PerplexityBot.",
               "Remove those blocks, unless you block them on purpose.",
               "Keep private areas blocked with their own rules."),
    "G1.02": F(OWNER, "Decide whether AI companies may train on your content (GPTBot, ClaudeBot, Google-Extended, "
                      "Applebot-Extended).",
               "Ask the developer to set robots.txt to match that decision.",
               "Write the decision down so later changes don't undo it."),
    "G1.03": F(DEV, "Check the firewall or CDN settings (for example Cloudflare's bot rules) for blocks on AI tools.",
               "Allow the AI search tools you want to be found by.",
               "Keep rate limits for abusive traffic."),
    "G1.04": F(DEV, "Have the server send the main content of {pages} in the HTML, with server-side rendering or "
                    "pre-rendering.",
               "Check by viewing the page source: the main text should be there."),
    "G1.05": F(DEV, "Put the key facts on {pages} (prices, address, hours, product details) in the HTML the server "
                    "sends.",
               "Don't load them only through JavaScript or show them only in images."),
    "G1.06": F(DEV, "Optional: add /llms.txt, listing your key pages with one line about each.",
               "It isn't known to affect rankings; it only helps tools that read it."),
    # ---------------------------------------------------------------- G2 Facts & citability
    "G2.01": F(CONTENT, "List the facts only your business can state: numbers, locations, years, awards and the "
                        "specifics of your offer.",
               "Add them to {pages} in plain sentences.",
               "Keep them identical on listings and profiles."),
    "G2.02": F(CONTENT, "Add what only you know to {pages}: your own numbers, real customer examples and local "
                        "knowledge.",
               "Name the experts behind it.",
               "Replace generic text that any competitor could publish."),
    "G2.03": F(CONTENT, "Next to each figure or award on {pages}, name the source and the year.",
               "Link to the source where you can.",
               "Remove figures you can't back up."),
    "G2.04": F(CONTENT, "In the first lines of {pages}, state the business name, what it does and where.",
               "Use the same business name everywhere."),
    "G2.05": F(CONTENT, "Write one self-contained paragraph of 50 to 200 words on {pages}.",
               "Make it state facts about the page's topic and name the business, so it can be quoted on its own."),
    "G2.06": F(CONTENT, "Confirm the correct figure for each fact that differs; the technical details list them.",
               "Update every page, listing and profile that states it."),
    # ---------------------------------------------------------------- G3 AI voice
    "G3.01": F(MARKETING, "Check which sources AI answers draw on for your category (the cited sites).",
               "Get listed and reviewed there: directories, review sites and comparison articles.",
               "Keep your facts consistent across them."),
    "G3.02": F(MARKETING, "Review which competitors AI mentions, and for which questions.",
               "Compare what they publish, and where they are listed, with your own pages.",
               "Close the biggest gaps first."),
    "G3.03": F(MARKETING, "Strengthen the facts AI uses to describe you: a clear offering, locations and numbers.",
               "Make them consistent on the site and on major listings."),
    "G3.04": F(MARKETING, "Find where the wrong or negative claim comes from: reviews, old listings or articles.",
               "Correct it at the source, or respond publicly where you can't.",
               "State the correct facts clearly on your site."),
    "G3.05": F(MARKETING, "Make the facts that earn mentions identical on the site, listings and profiles.",
               "Check the AI answers again next month to see whether the mentions hold."),
    # ---------------------------------------------------------------- G4 Citations
    "G4.01": F(CONTENT, "Take the searches in the technical details where AI cites other sites.",
               "Publish or improve a page that answers each one directly, with facts and sources."),
    "G4.02": F(MARKETING, "Review the sites AI cites for your searches.",
               "Get listed, reviewed or mentioned on the ones relevant to you."),
    "G4.03": F(DEV, "Check the wrong addresses AI gives for you; the technical details list them.",
               "Forward any that look like real old addresses to the right page with 301 redirects.",
               "Use your main addresses consistently on listings and profiles."),
    "G4.04": F(CONTENT, "Compare your pages with the traits that cited pages share; the technical details list them.",
               "Add the ones that fit your content, such as dates, sources, clear answers or tables."),
    # ---------------------------------------------------------------- G5 Brand accuracy
    "G5.01": F(MARKETING, "List the facts AI states wrongly; the technical details show them.",
               "State the correct facts clearly on the site, and fix them on major listings.",
               "Check the AI answers again after a few weeks."),
    "G5.02": F(CONTENT, "Publish distinctive, quotable facts on key pages and listings: what you offer, where, for "
                        "whom, and numbers.",
               "Remove generic phrases that could describe any competitor."),
    "G5.03": F(CONTENT, "Take the offerings AI leaves out; the technical details list them.",
               "Give each a clear page or section on the site, and add it to your listings."),
    "G5.04": F(MARKETING, "Use one consistent business name and address everywhere.",
               "Ask the developer to link your official profiles with sameAs in the Organization structured data.",
               "Correct listings that mix you up with the other business."),
    # ---------------------------------------------------------------- G6 Entity footprint
    "G6.01": F(MARKETING, "Complete and verify the Google Business Profile.",
               "Keep the name, address and website identical everywhere.",
               "Ask the developer to add Organization structured data with sameAs links to the official profiles."),
    "G6.02": F(MARKETING, "If the business is notable (covered by independent press), an independent editor can "
                          "create a Wikidata item with the official website.",
               "Don't create or edit Wikipedia pages about yourself."),
    "G6.03": F(MARKETING, "Create or claim the missing listings named in the technical details.",
               "Use the same name, address, phone and website on each.",
               "Complete each profile with photos and details."),
    "G6.04": F(DEV, "List the official profiles: social accounts, listings and Wikidata.",
               "Add them to sameAs in the Organization structured data."),
    "G6.05": F(MARKETING, "Search the brand name and note the other sites that appear.",
               "Strengthen your own pages and profiles for the name: the brand in page titles, complete profiles.",
               "If another business shares the name, add distinguishing details: your location and what you do."),
}


def _path(url: str) -> str:
    parts = urlsplit(url)
    return parts.path if parts.path not in ("", "/") else (parts.netloc or url)


def pages_phrase(pages: list[str]) -> str:
    paths = list(dict.fromkeys(_path(p) for p in pages))
    if not paths:
        return "the affected pages"
    if len(paths) == 1:
        return paths[0]
    if len(paths) == 2:
        return f"{paths[0]} and {paths[1]}"
    return f"{paths[0]}, {paths[1]} and {len(paths) - 2} more"


def fix_steps(finding: dict) -> dict:
    """The steps to fix one finding, with its own pages filled in, and who does them. Empty when unknown."""
    item = STEPS.get(finding.get("check_id", ""))
    if item is None:
        return {"owner": "", "steps": []}
    where = pages_phrase((finding.get("scope") or {}).get("pages", []))
    return {"owner": item.owner, "steps": [s.replace("{pages}", where) for s in item.steps]}
