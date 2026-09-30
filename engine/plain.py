"""Plain-language explanations of every check, for management and clients (user decision, 2026-09-29).

Two layers, so an explanation is never missing and never made up:

- LIBRARY: one reviewed entry per check. `name` is what the check looks at (for passes and "couldn't
  check" lists); `problem` is the issue in plain words; then what it means, why it matters to the
  business, an everyday comparison and what to do. Written once, never generated: free, instant and
  identical on every run, for every kind of business.
- Site cases: one model call per run writes a sentence per issue from that issue's own pages and numbers
  ("On 3 of the 5 pages we measured, the page takes about 1.0 s to react to a tap"). A sentence is kept
  only if every number and page path in it appears in that issue's data; otherwise a template is used.

GLOSSARY explains the technical terms that appear in an issue's technical details.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from engine.fix_steps import fix_steps
from engine.llm import LLMClient, LLMError, load_prompt
from engine.schemas import Finding, fingerprint_of


@dataclass(frozen=True)
class Plain:
    name: str
    problem: str
    meaning: str
    why: str
    analogy: str
    action: str


P = Plain
LIBRARY: dict[str, Plain] = {
    # ---------------------------------------------------------------- S1 Crawl & index health
    "S1.01": P("Pages open without errors", "Some links lead to error pages",
               "When someone opens these addresses, the site answers with an error (such as 'page not found') "
               "instead of the page.",
               "Visitors hit a dead end and leave, and Google wastes its visits on pages that don't work.",
               "Like a signboard pointing customers to a shop that has closed.",
               "Fix or remove the broken links, or forward each old address to the closest working page."),
    "S1.02": P("Missing pages are reported honestly", "Empty pages pretend to be real pages",
               "Some pages show a 'not found' or empty message but tell search engines everything is fine.",
               "Google may list these empty pages in search, which disappoints the people who click them.",
               "Like a shop with its lights on and door open, but empty shelves inside.",
               "Make pages that don't exist report 'not found' properly, or add the missing content."),
    "S1.03": P("Links go straight to the right page", "Links bounce through several addresses first",
               "Opening these links sends the visitor through a chain of forwarding addresses before the real "
               "page loads.",
               "Each hop adds delay, and search engines may stop following a long chain.",
               "Like being sent from desk to desk before anyone serves you.",
               "Point every link directly at the final address."),
    "S1.04": P("Important pages can appear in Google", "Some important pages ask Google to hide them",
               "A hidden instruction on these pages asks search engines to leave them out of search results.",
               "Pages that ask to be hidden can't bring in visitors from Google, however good they are.",
               "Like hanging a 'closed' sign on a shop that is actually open.",
               "Remove the 'don't show' instruction from every page you want customers to find."),
    "S1.05": P("Search engines are allowed to read the site", "The site's rules file blocks search engines",
               "Every site has a small rules file (robots.txt) that tells search engines which pages they may "
               "visit. It currently blocks pages that matter.",
               "Pages search engines can't read rank poorly or not at all.",
               "Like a 'staff only' sign on the door to your showroom.",
               "Allow search engines to visit the pages that matter."),
    "S1.06": P("Each page names its official address", "Pages don't say which address is the official one",
               "The same page can be opened at slightly different web addresses. A small tag (canonical) tells "
               "Google which one is official, and it's missing here.",
               "Google may split a page's ranking strength between the copies or show the wrong version.",
               "Like signing documents with three spellings of your name: the records don't add up.",
               "Add a tag to each page that names its own official address."),
    "S1.07": P("Search engines get a list of the site's pages", "Search engines don't get a list of the site's pages",
               "A sitemap is a file that lists every page you want found. This site has no working one.",
               "Google finds new pages and notices updates more slowly.",
               "Like a shopping mall with no directory board at the entrance.",
               "Publish a sitemap listing every page you want in search, and point to it from the rules file."),
    "S1.08": P("The site opens at one address", "The site opens at several different addresses",
               "Versions of the address (with or without 'www', or 'http' instead of 'https') open separately "
               "instead of all leading to one.",
               "Google may treat them as separate sites and split their strength.",
               "Like a business listed under two phone numbers that don't forward to each other.",
               "Forward every version permanently to one main address."),
    "S1.09": P("Pages are distinct from each other", "Some pages are almost copies of each other",
               "These pages share nearly all their text, so they look like the same page twice.",
               "Google may show only one of them, or treat them as low-effort pages.",
               "Like handing out two brochures that differ only on the cover.",
               "Make each page clearly different, or merge them into one."),
    "S1.10": P("Pages are fully secure", "Some pages aren't fully secure",
               "Parts of these pages load over an unsecured connection.",
               "Browsers can show 'not secure' warnings that scare visitors off, and Google prefers secure pages.",
               "Like a bank branch with a broken lock on one door.",
               "Serve every page, image and script securely over https."),
    "S1.11": P("Pages declare their language", "Pages don't declare their language",
               "A small setting tells browsers and search engines which language a page is written in. It's "
               "missing here.",
               "Search engines and screen readers may treat the page as the wrong language.",
               "Like a library book with no language printed on the cover.",
               "Add the language setting (for example English) to every page."),
    # ---------------------------------------------------------------- S2 Page experience
    "S2.01": P("How fast the main content appears", "Pages take too long to show their main content",
               "This measures how long the biggest thing on the screen, usually the main picture or headline, "
               "takes to appear. Google calls it LCP and counts it in rankings.",
               "People leave pages that stay blank, and Google ranks slow pages lower on phones.",
               "Like a shop that keeps its shutter half down for several seconds after you arrive.",
               "Make the main picture or text load first: smaller images, loaded early, with less code in the way."),
    "S2.02": P("How fast pages react to a tap or click", "Pages react slowly when visitors tap or click",
               "This measures the delay between a visitor tapping a button and the page responding. Google calls "
               "it INP and counts it in rankings.",
               "A laggy page feels broken, so people tap again or leave, and Google ranks it lower on phones.",
               "Like a lift button that lights up a second or two after you press it.",
               "Reduce heavy scripts, especially chat, ad and tracking tools, so the page can respond at once."),
    "S2.03": P("Pages stay steady while loading", "Page content jumps around while loading",
               "This measures how much the layout moves while the page loads, for example text jumping down when "
               "an image appears. Google calls it CLS.",
               "Visitors lose their place or tap the wrong thing, and Google counts it against the page.",
               "Like a menu card whose items rearrange themselves while you're reading it.",
               "Reserve space for images, banners and pop-ups before they load."),
    "S2.04": P("How fast the server starts responding", "The server is slow to start sending pages",
               "This measures how long the website's server takes to begin sending a page after someone asks for "
               "it. Google calls it TTFB.",
               "Everything else waits for this, so a slow start makes the whole page slow.",
               "Like a waiter who takes a long time to reach your table before you can even order.",
               "Speed up the server with caching, a content delivery network (CDN) and fewer redirects."),
    "S2.05": P("What slows the main content down", "The main content is held up at one loading step",
               "This splits the main content's loading time into steps (waiting for the server, finding the "
               "image, downloading it, drawing it) to show which step is slow.",
               "Knowing the slow step points developers straight to the fix.",
               "Like a parcel tracker showing the parcel is stuck at the warehouse, not on the road.",
               "Fix the slowest step first, as shown in the technical details."),
    "S2.06": P("The main picture is set up to load quickly", "The main picture loads late",
               "The biggest picture on the page is set to load only after scrolling or after code runs, so the "
               "browser starts downloading it late.",
               "The page looks empty for longer, and slow main content lowers Google rankings.",
               "Like a shop that sets up its window display only after customers have walked past.",
               "Load the main picture straight away, compressed, and marked as high priority."),
    "S2.07": P("Pages are set up for phones", "Pages aren't set up properly for phones",
               "These pages miss the basic setting that makes a page fit a phone screen, or have text and buttons "
               "too small to use.",
               "Most visitors use phones; a page that doesn't fit makes them pinch, zoom or leave.",
               "Like a newspaper folded so small you need a magnifying glass to read it.",
               "Add the phone display setting and make text and buttons big enough to tap."),
    "S2.08": P("Code doesn't hold the page up", "Heavy code holds the page up",
               "Large scripts must finish loading before the page can show, and some of that code is never used.",
               "Every extra second of waiting loses visitors and lowers rankings.",
               "Like waiting for every member of staff to arrive before any table is served.",
               "Load extras such as chat, ads and trackers after the page shows, and remove unused code."),
    # ---------------------------------------------------------------- S3 Search metadata
    "S3.01": P("Every page has its own title", "Some pages share a title or have none",
               "The title is the blue headline Google shows for a page in search results. These pages have none, "
               "or share one with other pages.",
               "Google can't tell the pages apart, so they compete with each other and look vague in results.",
               "Like several books on a shelf with the same name on the spine.",
               "Give every page a unique title that says what that page is about."),
    "S3.02": P("Titles are the right length", "Titles are too long or too short",
               "Google shows about 60 characters of a title. Longer titles get cut off; very short ones waste the "
               "space.",
               "A cut-off title can hide the most important words, so fewer people click.",
               "Like a shop sign so long that the end of your name falls off the board.",
               "Keep titles between 30 and 60 characters, with the key words first."),
    "S3.03": P("Titles describe their page", "Page titles don't clearly say what the page is about",
               "The titles are vague, stuffed with keywords or bury the main topic.",
               "Searchers pick the result that clearly matches what they want; vague titles get skipped.",
               "Like a restaurant sign that just says 'Food' instead of what's on the menu.",
               "Use titles that lead with the page's topic. We propose new ones in the technical details."),
    "S3.04": P("Titles match the page heading", "Titles and page headings say different things",
               "The title shown in Google and the main heading on the page describe different topics.",
               "Google may replace the title with its own guess, and visitors feel misled.",
               "Like a book whose cover and first chapter carry different titles.",
               "Make each page's title and main heading describe the same topic."),
    "S3.05": P("Every page has its own search description", "Search descriptions are missing or badly sized",
               "The description is the short grey text under the title in Google. Some pages have none, or one "
               "that is too long or too short.",
               "Without a good one, Google picks random text from the page, which rarely persuades anyone to click.",
               "Like a shop window with a blank sheet instead of a display.",
               "Write a unique description of 70 to 155 characters for each page."),
    "S3.06": P("Search descriptions are accurate and specific", "Search descriptions are vague or claim too much",
               "The short texts under your titles in Google are generic, or make claims the page doesn't back up.",
               "Vague or overblown descriptions get fewer clicks and can cost trust.",
               "Like an advert promising 'the best in India' without saying what you actually offer.",
               "Use specific, honest descriptions with one concrete detail. We propose new ones in the technical "
               "details."),
    "S3.07": P("Shared links show a proper preview", "Shared links show a poor preview",
               "Small tags (Open Graph) decide the picture, title and text shown when a page is shared on "
               "WhatsApp, LinkedIn or Facebook. They're missing here.",
               "A plain or broken preview gets far fewer clicks when people share your pages.",
               "Like forwarding a brochure with the cover torn off.",
               "Add a sharing title, description and image to each key page."),
    # ---------------------------------------------------------------- S4 On-page content
    "S4.01": P("Each page has one clear main heading", "Pages lack one clear main heading",
               "The main heading (H1) is the big title on the page itself. These pages have none, or several "
               "competing ones.",
               "Readers and search engines use it to understand what the page is about; without it the topic is "
               "unclear.",
               "Like a newspaper page with no headline, or three headlines of the same size.",
               "Give each page exactly one main heading that names its subject."),
    "S4.02": P("Headings are in a sensible order", "Page headings are out of order",
               "Headings should step down from the main heading to sections and sub-sections, like a table of "
               "contents. These pages skip levels or use headings just for decoration.",
               "Search engines and screen readers use headings as the page outline; a jumbled outline hides the "
               "structure.",
               "Like a report whose chapter numbers jump from 1 to 4 and back to 2.",
               "Use headings in order, and use design styles, not headings, for decoration."),
    "S4.03": P("Pages open with what visitors came for", "Pages don't open with what visitors came for",
               "The first lines of the page don't quickly confirm the visitor is in the right place or answer "
               "their main need.",
               "Visitors decide in seconds; if the opening misses, they go back to the search results.",
               "Like a salesperson who starts with the company history when you asked the price.",
               "Open with a short summary that answers the main question the page exists for."),
    "S4.04": P("The page type matches what searchers want", "This kind of page isn't what Google shows for the search",
               "For the main search this page targets, Google mostly shows a different type of page, for example "
               "guides instead of product pages.",
               "Google ranks the type of page searchers prefer; a different type rarely ranks, however good.",
               "Like opening a sweet shop on a street where everyone is looking for a chemist.",
               "Match the type of page that ranks, or target a search your type of page can win."),
    "S4.05": P("Pages cover what the top results cover", "Pages miss topics the top results all cover",
               "The pages at the top of Google for this search all mention certain topics that this page doesn't.",
               "Searchers expect those topics; a page without them satisfies the search less and ranks lower.",
               "Like a phone brochure that never mentions the battery, when every rival's does.",
               "Add a short section on each missing topic, using facts you can stand behind."),
    "S4.06": P("Pages have enough of their own content", "Some pages have very little text of their own",
               "Apart from menus and footers, these pages have little text of their own.",
               "Thin pages rarely rank and give AI assistants nothing to quote.",
               "Like a shop window with a price tag but no product in it.",
               "Add real content: what the page offers, key facts and answers to common questions."),
    "S4.07": P("Offers and prices show dates", "Offers and prices have no dates",
               "Prices or offers are shown without saying when they apply or when they were last updated.",
               "Customers can't tell if a deal is still valid, and AI assistants may repeat outdated prices.",
               "Like a 'SALE' poster with no end date that has been on the wall for a year.",
               "Add validity dates to offers and 'as of' dates to prices."),
    "S4.08": P("Text is easy to read", "Text is hard to read",
               "Sentences and paragraphs are long and dense.",
               "Visitors skim; hard text loses them and is less likely to be quoted in answers.",
               "Like a user manual written as one long paragraph.",
               "Use shorter sentences, short paragraphs and lists."),
    "S4.09": P("Keywords are used naturally", "Pages repeat the same phrase too often",
               "A search phrase is repeated so often that the text reads unnaturally.",
               "It reads as spam to people and to search engines, which can push the page down.",
               "Like a salesperson who says the product name in every sentence.",
               "Use the phrase where it matters (title, heading, opening) and vary the wording elsewhere."),
    # ---------------------------------------------------------------- S5 Keyword themes
    "S5.01": P("Every topic customers search for has a page", "Topics customers search for have no page",
               "Customers search for these topics, but no page on the site is dedicated to them.",
               "Those searches go to competitors and comparison sites instead.",
               "Like customers asking a shop for an item it sells but has no shelf for.",
               "Give each important topic its own page or a clear section."),
    "S5.02": P("Pages don't compete for the same search", "Several pages compete for the same search",
               "Two or more pages target the same search, so Google has to guess which one to show.",
               "The pages split their strength and often neither ranks well.",
               "Like two salespeople from the same shop pitching to one customer against each other.",
               "Choose one page for each topic, and merge or refocus the others."),
    "S5.03": P("Each page has a clear job", "Some pages don't have a clear job",
               "It isn't clear which customer need or search each of these pages serves.",
               "Pages without a clear purpose rarely rank for anything.",
               "Like a shop aisle holding a random mix of products with no sign.",
               "Decide the one purpose of each page and shape its content around it."),
    "S5.04": P("Places customers search for are covered", "Places customers search for have no page",
               "Customers search with a place name (a city, area or landmark), but no page names that place.",
               "Local searches go to pages that mention the place.",
               "Like a courier that serves a city but never lists it on its route board.",
               "Cover each place customers search for with a page or section that names it."),
    "S5.05": P("Recurring customer topics are addressed", "Topics customers keep searching for appear nowhere",
               "These topics come up again and again in search data, but the site never mentions them.",
               "Search engines and AI assistants find nothing on your site to match these searches.",
               "Like a restaurant that keeps being asked for a dish it never puts on the menu.",
               "Decide which of these topics fit the business, and cover them."),
    # ---------------------------------------------------------------- S6 SERP landscape
    "S6.01": P("How visible the site is in Google", "The site rarely appears on the first page for customer searches",
               "For searches that don't include the business name, the site isn't in Google's top 10 results.",
               "Customers who don't already know the name never see the business.",
               "Like a shop that only people who already have its address can find.",
               "Target searches the site can realistically win, and strengthen those pages."),
    "S6.02": P("Who the site competes with in search", "Search results are crowded with other kinds of sites",
               "We sorted the sites that rank for your searches into direct competitors, comparison sites, "
               "directories and publishers.",
               "Knowing who you're up against shows whether to compete, partner or get listed.",
               "Like surveying which shops line your street before planning your window display.",
               "Review the competitor list and plan against the direct competitors."),
    "S6.03": P("What Google shows besides plain links", "Google shows extra boxes the site isn't part of",
               "Google results often include extra features such as AI answers, question boxes, maps and videos.",
               "These features take attention away from ordinary links; being in them brings visitors.",
               "Like billboards placed above the shop signs on a street.",
               "Prepare content in the formats these features use."),
    "S6.04": P("What top competitors' pages have", "Top-ranking pages have things this page lacks",
               "Most pages at the top for your searches include certain elements (such as prices, ratings or "
               "specific details) that your page doesn't.",
               "These shared elements are part of why those pages rank and get chosen.",
               "Like every busy stall in a market showing prices while yours doesn't.",
               "Add the elements that genuinely fit your business (listed in the technical details)."),
    "S6.05": P("Content depth compared with competitors", "The page is much shorter than competing pages",
               "Pages that rank for the same search have much more content than yours.",
               "Deeper pages answer more questions and tend to rank better.",
               "Like a two-line label next to a competitor's full brochure.",
               "Add the useful detail customers look for; length alone isn't the goal."),
    # ---------------------------------------------------------------- S7 Internal linking
    "S7.01": P("Every page is linked from other pages", "Some pages aren't linked from anywhere",
               "No other page on the site links to these pages.",
               "Visitors and search engines can't find pages that nothing links to.",
               "Like a room in a building with no corridor leading to it.",
               "Link these pages from related pages and menus."),
    "S7.02": P("Important pages are easy to reach", "Important pages are buried too deep",
               "It takes many clicks from the homepage to reach these pages.",
               "Search engines treat deeply buried pages as less important, and visitors give up.",
               "Like keeping your best-selling product in the back storeroom.",
               "Link key pages from the homepage or the main menu."),
    "S7.03": P("Important pages get links from other pages' text", "Important pages get few links from other pages' text",
               "Key pages are linked mostly from menus, not from within the text of related pages.",
               "Links inside text tell search engines what a page is about and how important it is.",
               "Like a shop assistant who never recommends your best product in conversation.",
               "Link to key pages from relevant sentences on other pages."),
    "S7.04": P("Link text says where it goes", "Links use vague words like 'click here'",
               "The clickable words of some links are generic ('know more', 'click here') or empty.",
               "Visitors and search engines can't tell what's behind the link.",
               "Like signposts that all just say 'this way'.",
               "Use link words that name the page they lead to."),
    "S7.05": P("Links point at final addresses", "Links point at old addresses that forward elsewhere",
               "Links on the site go to addresses that then forward the visitor to a different page.",
               "Every forward slows visitors down and wastes search engines' time.",
               "Like a visiting card with an old office address and a 'we've moved' notice.",
               "Update the links to point at the final addresses."),
    "S7.06": P("Key pages link to related pages", "Key pages link onward only through menus",
               "These pages don't link to related pages from their own text, only from menus and footers.",
               "Links in the text guide visitors to their next step and show search engines how pages relate.",
               "Like a guide who only ever points at the map on the wall.",
               "Add links in the text to related pages where they are mentioned."),
    "S7.07": P("Related pages link to each other", "Related pages mention each other without linking",
               "Pages mention topics that are covered elsewhere on the site but don't link to them.",
               "Readers and search engines miss the connection.",
               "Like a brochure that says 'see our other offers' without saying where.",
               "Add the suggested links."),
    # ---------------------------------------------------------------- S8 Structured data
    "S8.01": P("Business information code is written correctly", "Some of the hidden business information code has errors",
               "Pages carry hidden code (structured data) that describes the business to search engines. Some of "
               "it has formatting errors.",
               "Strict readers may ignore the broken code, so that information is lost.",
               "Like a form filled in with ink blots over some boxes.",
               "Fix the formatting of that code; the technical details show where."),
    "S8.02": P("Business information code is complete", "The hidden business information is missing required details",
               "The structured data describing products, the business or offers leaves out fields Google requires.",
               "Incomplete information can't earn special search displays such as ratings or prices.",
               "Like an application form returned because mandatory boxes are blank.",
               "Add the missing required details."),
    "S8.03": P("Business information says what kind of business this is",
               "The hidden business information doesn't say what kind of business this is",
               "Search engines understand a business partly from specific information types (for example "
               "Product, Hotel or LocalBusiness). The types that fit this business are missing.",
               "Search engines and AI may misunderstand what you offer.",
               "Like a company registered without a trade category.",
               "Add the information type that matches your business, on the pages it describes."),
    "S8.04": P("Business information matches the page", "The hidden business information describes something else",
               "The structured data says one thing (another business, place or offer) while the page shows "
               "something different.",
               "Search engines and AI treat this code as facts, so they learn the wrong details.",
               "Like a shop's name board showing a different shop's name.",
               "Replace it with information that matches this page's business."),
    "S8.05": P("Business information uses current types", "Some business information uses types Google no longer rewards",
               "Some structured data (such as FAQ markup) no longer earns special displays in Google.",
               "It does no harm, but don't expect extra visibility from it.",
               "Like a coupon the counter still accepts but no longer advertises.",
               "No action needed; just don't add more of it expecting results."),
    "S8.06": P("The business is described consistently", "The business is described in different ways",
               "The hidden information names or describes the business differently in different places.",
               "Search engines and AI may treat it as separate businesses.",
               "Like signing documents with different versions of your name.",
               "Use one name and one description everywhere, linked together."),
    "S8.07": P("Review information follows Google's rules", "Review information breaks Google's rules",
               "The information about reviews and ratings doesn't follow Google's policy, for example a business "
               "rating itself.",
               "Google can ignore it or penalise the page.",
               "Like a restaurant printing its own five-star reviews on the menu.",
               "Only mark up genuine reviews shown on the page, as Google's policy allows."),
    # ---------------------------------------------------------------- S9 Local & entity
    "S9.01": P("Name, address and phone match everywhere", "Name, address or phone differ between places",
               "The business name, address or phone number is different on the site, in its hidden information "
               "and on Google Maps.",
               "Search engines and AI may mix the business up, and customers may call the wrong number.",
               "Like two different addresses printed on your letterhead.",
               "Use an identical name, address and phone number everywhere."),
    "S9.02": P("Location pages have the basics", "A location page is missing basic details",
               "A page for a place customers visit is missing things like the address, opening hours, a map or "
               "local details.",
               "Without them the page doesn't show for local searches and can't answer 'where' and 'when'.",
               "Like a branch signboard with no address or opening times.",
               "Add the full address with PIN code, the hours and a map link to the page."),
    "S9.03": P("The Google Maps listing is complete", "The Google Maps listing is missing or incomplete",
               "The business's Google Maps profile is missing, in the wrong category or doesn't link to the "
               "website.",
               "Maps listings drive local searches, directions and calls.",
               "Like being in the phone directory under the wrong category.",
               "Claim and complete the Google Business Profile: category, hours, phone and website."),
    "S9.04": P("The business shows in local map results", "The business doesn't show in local map results",
               "When Google shows a map of nearby businesses for your searches, yours isn't on it.",
               "The map box sits above ordinary results and gets many of the clicks.",
               "Like a street map of shops where yours isn't marked.",
               "Strengthen the Maps listing with reviews, photos and complete details."),
    "S9.05": P("Contact details use Indian formats", "Contact details aren't in a usable format",
               "The page has no tap-to-call phone number, no PIN code, or numbers without the +91 country code.",
               "Phone visitors can't call in one tap, and local search reads locations from PIN codes.",
               "Like a visiting card with a phone number but no area code.",
               "Add the address with its PIN code and a tap-to-call number with +91."),
    "S9.06": P("Service areas are stated", "The areas the business serves aren't stated",
               "The site doesn't list the cities or areas it serves.",
               "Customers and search engines can't tell whether you cover their area.",
               "Like a delivery service that never says where it delivers.",
               "List the areas you serve on the site."),
    # ---------------------------------------------------------------- S10 Trust
    "S10.01": P("The site says who runs the business", "The 'about us' information is missing or thin",
                "The site doesn't clearly say who runs the business, its history or its credentials.",
                "People and AI assistants trust businesses that say who they are.",
                "Like a shop with no name board and no owner's details.",
                "Publish an about page: who you are, since when, and your credentials."),
    "S10.02": P("Contact details are easy to find", "Contact details are missing or hard to find",
                "The contact page lacks details such as the address, phone or email as plain text.",
                "Businesses that are hard to reach lose customers and look less trustworthy.",
                "Like a shop whose door has no bell and no phone number.",
                "List full contact details as plain text on the contact page."),
    "S10.03": P("Articles show who wrote them", "Articles don't say who wrote them",
                "Articles or guides have no named author with a short biography.",
                "Advice from a named expert is more believable to readers and search engines.",
                "Like health advice in a leaflet with no doctor's name on it.",
                "Add author names and short biographies to articles."),
    "S10.04": P("Content shows when it was published or updated", "Content has no dates",
                "Pages don't show when they were written or last updated.",
                "Readers can't tell whether the information is current.",
                "Like a notice board full of undated notices.",
                "Show publish and update dates on content pages."),
    "S10.05": P("Customer policies are published", "Customer policies are missing or incomplete",
                "Key policies (such as returns, refunds, cancellation, shipping or privacy) are missing or only "
                "partly explained.",
                "Customers check policies before buying or booking; missing ones cost sales and trust.",
                "Like a shop that won't tell you its return rules until after you pay.",
                "Publish each policy in plain text and link it from the footer and the checkout or booking steps."),
    "S10.06": P("Legally expected information is shown", "Legally expected information is missing",
                "Information businesses in your sector are expected to show (for example a grievance officer or "
                "registration details) is missing or incomplete.",
                "Regulators and customers expect it, and its absence is a warning sign. This is a prompt for your "
                "compliance team, not legal advice.",
                "Like a clinic that doesn't display its registration certificate.",
                "Ask your compliance team to confirm and add each missing item."),
    "S10.07": P("Reviews are genuine and attributed", "Reviews don't show who wrote them or when",
                "Testimonials on the site are anonymous or undated.",
                "Named, dated reviews are believable; anonymous praise isn't.",
                "Like a poster saying 'customers love us' with no names on it.",
                "Show each reviewer's name (or the source) and the date, and link to the review site."),
    "S10.08": P("Prices are clear and complete", "Prices or fees aren't fully stated",
                "Prices, taxes or fees are missing, or appear only at checkout.",
                "Hidden costs cost trust and invite complaints, and AI assistants can't quote your prices.",
                "Like a menu that adds a surprise service charge only on the bill.",
                "Show full prices including taxes and fees, or a clear 'from' price and what it includes."),
    # ---------------------------------------------------------------- A1 Answer coverage
    "A1.01": P("Customers' real questions are answered", "Questions customers actually ask aren't answered",
               "We collected questions real people ask Google about your business and category. The site "
               "doesn't answer these.",
               "When your site doesn't answer, Google and AI assistants quote other sites instead.",
               "Like a help desk with no answers to the questions customers ask most.",
               "Add short, direct answers to these questions on the right pages; we draft some."),
    "A1.02": P("Common questions for your kind of business are answered",
               "Common questions for your kind of business aren't fully answered",
               "Questions customers usually ask in your category are answered only partly or not at all.",
               "Unanswered questions send customers elsewhere.",
               "Like a car showroom that can't tell you the mileage.",
               "Add clear answers; we draft some."),
    "A1.03": P("Answers match the business's own facts", "Some answers contradict the business's own facts",
               "Answers on the site disagree with facts the site states elsewhere.",
               "Contradictions confuse customers and AI assistants.",
               "Like two brochures giving different prices for the same item.",
               "Correct the answers to match the confirmed facts."),
    "A1.04": P("Every topic customers ask about is covered", "Whole topics customers ask about are missing",
               "Entire topics customers ask about (for example delivery or support) aren't covered anywhere on "
               "the site.",
               "Neither Google nor AI assistants can use your site to answer these topics.",
               "Like a catalogue missing a whole product category.",
               "Add a short, factual section for each missing topic."),
    # ---------------------------------------------------------------- A2 Answer structure
    "A2.01": P("Sections start with a direct answer", "Sections don't start with a direct answer",
               "These sections take a while to get to the point instead of answering in the first sentence.",
               "Google and AI assistants prefer text that answers straight away, and quote it more often.",
               "Like asking for directions and hearing the town's history first.",
               "Open each section with a direct answer of 40 to 60 words; we draft some."),
    "A2.02": P("Headings are phrased as customer questions", "Headings don't match how people ask",
               "Section headings are labels ('Features', 'Services') rather than the questions customers type.",
               "Search engines and AI match questions to headings; label headings get overlooked.",
               "Like an FAQ page with topic names instead of questions.",
               "Rephrase key headings as the questions customers ask, with the answer right below."),
    "A2.03": P("Paragraphs make sense on their own", "Paragraphs don't make sense on their own",
               "Paragraphs lean on earlier text ('as mentioned above', 'this') so they can't be quoted alone.",
               "AI answers quote single paragraphs; unclear ones get skipped.",
               "Like a line taken out of a conversation that makes no sense alone.",
               "Rewrite key paragraphs so each names its subject and stands on its own."),
    "A2.04": P("Information uses lists and tables where it helps", "Some information would work better as a list or table",
               "Steps, comparisons or options are written as paragraphs.",
               "Google and AI assistants often show lists and tables directly in their answers.",
               "Like a recipe written as one paragraph instead of steps.",
               "Turn these sections into lists, steps or tables."),
    "A2.05": P("Answer paragraphs are short", "Answer paragraphs are too long",
               "Paragraphs that answer questions are long and dense.",
               "Short answers are easier to read and more likely to be shown in search.",
               "Like a full-page reply to a yes-or-no question.",
               "Keep answers to a few short sentences."),
    "A2.06": P("Answers are readable by search engines", "Some answers are hidden from search engines",
               "Some answers appear only after a click or are loaded by code, so they aren't in the page search "
               "engines read.",
               "Search engines and AI may not see those answers at all.",
               "Like keeping the answers in a locked drawer during an inspection.",
               "Put the answer text in the page itself; it can still be folded away visually."),
    "A2.07": P("Pages let search engines show their text", "Pages stop search engines from showing their text",
               "A setting on these pages limits how much text Google may show or quote.",
               "Google and AI can't quote the page in their answers.",
               "Like a book that forbids reviewers from quoting it.",
               "Remove the restriction unless it's there on purpose."),
    # ---------------------------------------------------------------- A3 Journey
    "A3.01": P("Each step of the customer journey is covered", "Steps of the customer journey are missing",
               "Customers go through steps: discover, compare, plan, buy or book, and get help afterwards. The "
               "site has little or nothing for some of them.",
               "Customers drop off at the steps the site doesn't support.",
               "Like a shop with a showroom but no billing counter or returns desk.",
               "Add a page, section or tool for each weak step."),
    "A3.02": P("Customers have the tools they need", "Tools customers need are missing or hard to find",
               "Tools needed to act (such as search, a booking or application form, a cart, order tracking or a "
               "price guide) are missing, hidden or only appear after code runs.",
               "Customers can't take the next step, and AI assistants can't see these tools.",
               "Like a bank branch with no counter for deposit slips.",
               "Make each tool visible and working on the page that needs it."),
    "A3.03": P("Pages lead on to the next step", "The page doesn't lead on to the next step",
               "The page gives no clear way to move on to buying, booking or enquiring, except perhaps through "
               "the menu.",
               "Interested visitors have nowhere to go, so they leave.",
               "Like a salesperson who explains everything but never offers to take the order.",
               "Add a clear call to action in the page content."),
    "A3.04": P("Content matches what customers ask at each step", "Customers ask about steps the site barely covers",
               "Customers search and ask questions at journey steps where the site has little or no content.",
               "Other sites answer those customers instead.",
               "Like a help desk that's closed during the hours most customers call.",
               "Cover the steps customers ask about first, starting with their questions."),
    # ---------------------------------------------------------------- A4 Snippets & PAA
    "A4.01": P("Chances to appear in Google's answer box", "Google's answer box goes to other sites",
               "For some searches Google shows a highlighted answer at the top. Another site holds it, and yours "
               "could compete.",
               "The answer box gets a large share of clicks and is read aloud by voice assistants.",
               "Like the 'staff pick' shelf at the front of a bookshop.",
               "Answer those searches directly, in the format Google shows (a short paragraph, list or table)."),
    "A4.02": P("Answers to 'People also ask' questions", "Questions Google suggests aren't answered on the site",
               "Google shows a 'People also ask' box of related questions for your searches. Your site doesn't "
               "answer them.",
               "Answering them can get your site into that box and helps AI assistants.",
               "Like the follow-up questions a customer asks after the first one, with no answers ready.",
               "Answer these questions under question headings on the most relevant page."),
    "A4.03": P("Answers use the format Google prefers", "Answers are in a different format than Google shows",
               "Google shows the answer for these searches as a list or table, but yours is a paragraph, or the "
               "other way round.",
               "Matching the format makes your answer more likely to be chosen.",
               "Like sending a form in the wrong layout.",
               "Present the answer in the format Google uses."),
    # ---------------------------------------------------------------- G1 AI crawler access
    "G1.01": P("AI search tools can read the site", "The site blocks AI search tools",
               "The site's rules file blocks the programs that AI search tools (such as ChatGPT search or "
               "Perplexity) use to read websites.",
               "Blocked sites can't be found or quoted in AI answers.",
               "Like refusing entry to a journalist who wants to recommend you.",
               "Allow AI search tools in the rules file, unless you block them on purpose."),
    "G1.02": P("AI training access (your choice)", "AI training access needs a deliberate decision",
               "The rules file decides whether AI companies may use your pages to train their models. This is a "
               "business choice.",
               "Blocking protects your content; allowing it may help AI models know your brand.",
               "Like deciding whether a library may keep a copy of your brochure.",
               "Decide deliberately, and set the rules file to match."),
    "G1.03": P("The site lets AI tools in like a browser", "The site's security turns AI tools away",
               "The site's firewall or security service blocks or challenges AI tools that try to read it.",
               "AI assistants can't read or quote your pages.",
               "Like a security guard turning away a reporter at the door.",
               "Let known AI tools through the firewall."),
    "G1.04": P("Main content is readable without running code", "Main content only appears after code runs",
               "The main text is loaded by JavaScript, so tools that read the page as sent see it almost empty.",
               "Most AI tools don't run code, so they can't read or quote this content.",
               "Like a shop window that only lights up when someone presses a hidden switch.",
               "Have the server send the main content as part of the page."),
    "G1.05": P("Key facts are readable without running code", "Key facts only appear after code runs",
               "Important facts (prices, addresses, key details) are added by code after the page loads.",
               "AI tools that don't run code miss these facts.",
               "Like price tags that only appear after you open the shop's app.",
               "Include key facts in the page itself."),
    "G1.06": P("AI guidance file (llms.txt)", "No AI guidance file (optional)",
               "llms.txt is an optional new file that summarises a site for AI tools. Its effect isn't proven yet.",
               "Nice to have, with no confirmed ranking benefit.",
               "Like a welcome leaflet a visitor may or may not read.",
               "Optional: add one if you like."),
    # ---------------------------------------------------------------- G2 Citable facts
    "G2.01": P("Key pages state distinctive facts", "Key pages lack distinctive facts",
               "Key pages don't state specific facts (numbers, names, places, dates) that set the business apart.",
               "AI assistants quote specific facts; generic text gives them nothing to use.",
               "Like a CV that says 'hard-working' but lists no achievements.",
               "Add concrete facts only your business can state."),
    "G2.02": P("Content is original and first-hand", "Pages read like generic content",
               "The text could have been written by any competitor; it has no first-hand details.",
               "Search engines and AI favour original, first-hand content.",
               "Like a menu copied from a template, with no house specials.",
               "Add what only you can say: your numbers, examples, local knowledge and named experts."),
    "G2.03": P("Claims name their sources", "Claims and figures don't name their sources",
               "Statistics, awards or claims are stated without saying where they come from.",
               "Unsourced claims are trusted less by people and by AI.",
               "Like saying 'studies show' without naming the study.",
               "Link to or name the source of each figure and award."),
    "G2.04": P("Pages say clearly who the business is", "Pages don't clearly say who the business is",
               "Key pages don't clearly state the business name, what it does and where it operates.",
               "AI assistants need this to connect your pages to the right business.",
               "Like a letter without a letterhead.",
               "State the business name, what it does and where, early on key pages."),
    "G2.05": P("Pages have paragraphs AI can quote", "Key pages have no paragraph an AI could quote",
               "No paragraph on these pages stands on its own and states a clear fact at a quotable length.",
               "AI answers tend to quote self-contained, factual paragraphs; without one, they quote other sites.",
               "Like giving a reporter no line worth quoting.",
               "Write at least one self-contained, factual paragraph of 50 to 200 words on each key page."),
    "G2.06": P("Brand facts are consistent", "Brand facts differ between pages",
               "The same fact (such as the number of customers or branches) appears with different values on "
               "different pages.",
               "AI assistants repeat whichever number they find, and contradictions look unreliable.",
               "Like two branches quoting different prices for the same product.",
               "Pick the correct figure and update every page that states it."),
    # ---------------------------------------------------------------- G3 AI share of voice
    "G3.01": P("How often AI assistants mention the brand", "AI assistants rarely mention the brand",
               "When we asked AI assistants the questions customers ask in your category, your brand was rarely "
               "or never named.",
               "Customers who ask AI for recommendations don't hear about you.",
               "Like a friend recommending places to eat and never mentioning yours.",
               "Earn mentions where AI answers draw from: listings, reviews and articles."),
    "G3.02": P("Which competitors AI assistants name", "AI assistants recommend others instead",
               "In the AI answers we sampled, other businesses were named where yours wasn't.",
               "These businesses take the recommendations your customers see.",
               "Like a travel guide that lists your neighbours but not you.",
               "Study what these competitors publish and where they are listed."),
    "G3.03": P("How prominently the brand is mentioned", "The brand is mentioned only in passing",
               "When AI assistants do mention you, it's low in the answer or only in passing.",
               "People act on the first recommendations they read.",
               "Like being the last name on a long list.",
               "Strengthen the facts and listings AI draws from."),
    "G3.04": P("How AI assistants describe the brand", "AI answers present the brand negatively",
               "Some AI answers describe the brand unfavourably.",
               "Negative framing steers customers away.",
               "Like a friend who adds 'but I've heard bad things' whenever they mention you.",
               "Find where the claim comes from (reviews, old listings) and address it there."),
    "G3.05": P("Consistency across AI assistants", "AI assistants disagree about the brand",
               "One assistant mentions you for a question while another doesn't.",
               "Your visibility depends on which assistant a customer happens to use.",
               "Like being in one city guide and missing from another.",
               "Make the facts that earn mentions consistent everywhere AI reads."),
    # ---------------------------------------------------------------- G4 Citation sources
    "G4.01": P("AI answers link to the site", "AI answers rarely link to the site",
               "Google's AI answers link to your site only when people search your name, not for general "
               "searches.",
               "For general searches, AI sends readers to other sites.",
               "Like being quoted in the news only when the story is about you.",
               "Publish pages that directly answer these searches."),
    "G4.02": P("Which sites AI answers rely on", "AI answers rely on other sites for your topics",
               "The sources AI answers cite for your topics are other websites, listings or social sites.",
               "AI learns about your category from these sites; if you aren't there, you aren't in the answer.",
               "Like journalists always calling the same few experts, none of them you.",
               "Get listed and mentioned on the sites AI cites."),
    "G4.03": P("Web addresses AI assistants give for you", "AI assistants give wrong or broken addresses for you",
               "When asked directly, AI models write out web addresses for your business, and some are wrong or "
               "don't exist.",
               "Customers may follow a broken or wrong link.",
               "Like a directory printing your old phone number.",
               "Keep your main addresses consistent everywhere so AI learns the right ones."),
    "G4.04": P("What pages AI cites have in common", "Pages AI cites share traits yours lack",
               "The pages AI answers cite share features (such as lists, prices or dates) that your pages don't.",
               "These traits make pages more likely to be cited.",
               "Like noticing that every prize-winning entry used the same format.",
               "Add the traits that fit your content."),
    # ---------------------------------------------------------------- G5 AI brand accuracy
    "G5.01": P("AI assistants state correct facts about the business", "AI assistants state wrong facts about the business",
               "We checked what AI assistants say about your business against your own facts; some statements "
               "are wrong.",
               "Customers get wrong information and may choose someone else.",
               "Like a directory listing the wrong opening hours.",
               "Make the correct facts clear and consistent on the site and on major listings."),
    "G5.02": P("AI descriptions of the business are specific", "AI assistants describe the business only in general terms",
               "AI answers mention you in vague terms, without specifics.",
               "Generic descriptions give customers no reason to choose you.",
               "Like a recommendation that says 'it's a shop' without saying why it's good.",
               "Publish distinctive, quotable facts on key pages and listings."),
    "G5.03": P("AI knows your key offerings", "AI assistants leave out key offerings",
               "AI answers leave out important things you offer.",
               "What AI doesn't know about, it can't recommend.",
               "Like a friend recommending your café without knowing you also do catering.",
               "State these offerings clearly on the site and on major listings."),
    "G5.04": P("AI doesn't confuse the business with another", "AI assistants confuse the business with another",
               "Some AI answers mix your business up with a different one.",
               "Customers get another business's details or reviews.",
               "Like post for your shop going to a namesake down the road.",
               "Use a consistent name and address, and link your official profiles, everywhere."),
    # ---------------------------------------------------------------- G6 Off-site footprint
    "G6.01": P("Google shows an information panel for the brand", "Google shows no information panel for the brand",
               "When people search your name, Google doesn't show a knowledge panel, the box with key facts about "
               "a business.",
               "That panel is where Google and its AI show who you are; without it, facts come from elsewhere.",
               "Like having no profile in the directory everyone checks first.",
               "Complete and verify your Google Business Profile, and keep your details identical everywhere."),
    "G6.02": P("The business is on Wikidata or Wikipedia", "The business isn't on Wikidata or Wikipedia",
               "Wikidata and Wikipedia are sources AI systems use to identify organisations, and there's no entry "
               "for this business.",
               "AI may know less about the business, or confuse it with another.",
               "Like being missing from the reference books a researcher checks first.",
               "If the business is notable, an independent editor can create an entry; don't write it yourself."),
    "G6.03": P("The business is on the platforms that matter for its type",
               "The business is missing from key platforms for its type",
               "Businesses like yours are expected on certain listing sites (such as booking, review or "
               "marketplace sites), and some are missing.",
               "Customers and AI look there first.",
               "Like a restaurant missing from the food apps everyone uses.",
               "Create and complete profiles on the missing platforms."),
    "G6.04": P("Official profiles are linked from the site", "The site doesn't link its official profiles",
               "The site's hidden business information doesn't list the business's official profiles (social "
               "media and listings).",
               "Search engines and AI can't confirm those profiles belong to you.",
               "Like a business card with no social handles or directory listings.",
               "List your official profiles in the site's business information."),
    "G6.05": P("What Google shows for the brand name", "Searches for the brand name show other sites",
               "When people search your name, the results include other or unrelated sites.",
               "Customers looking for you may land somewhere else.",
               "Like people asking for your shop and being pointed to another.",
               "Strengthen your own pages and profiles for your brand name."),
}

# Technical terms that appear in the technical details, explained once (label, pattern, meaning).
GLOSSARY: tuple[tuple[str, str, str], ...] = (
    ("LCP", r"\bLCP\b", "Largest Contentful Paint: how long the biggest picture or text block takes to appear. "
                        "Under 2.5 seconds is good."),
    ("INP", r"\bINP\b", "Interaction to Next Paint: how long the page takes to react after a tap or click. "
                        "Under 0.2 seconds is good."),
    ("CLS", r"\bCLS\b", "Cumulative Layout Shift: how much the page jumps around while loading. Under 0.1 is good."),
    ("TTFB", r"\bTTFB\b", "Time to First Byte: how long the server takes to start sending the page."),
    ("TBT", r"\bTBT\b", "Total Blocking Time: how long code keeps the page too busy to respond, measured in a test."),
    ("Core Web Vitals", r"core web vital", "Google's three page-experience measures (LCP, INP and CLS), used in "
                                           "rankings."),
    ("Lighthouse", r"\blighthouse\b", "Google's free testing tool that scores a page's speed and quality."),
    ("Field data", r"field data", "Measurements from real visitors' browsers, collected by Google."),
    ("Canonical tag", r"canonical", "A tag that tells search engines which web address is the official one "
                                    "for a page."),
    ("noindex", r"noindex", "An instruction asking search engines not to show a page in results."),
    ("robots.txt", r"robots\.txt", "A small file that tells search engines and other tools which pages they may "
                                   "visit."),
    ("Sitemap", r"sitemap", "A file listing the pages a site wants search engines to find."),
    ("Redirect", r"redirect|\b30[1278]\b", "An automatic forward from one web address to another."),
    ("404", r"\b404\b", "The 'page not found' error."),
    ("HTTPS", r"\bhttps\b(?!:)|mixed content|not secure","The secure version of a web connection (the padlock in the browser)."),
    ("H1", r"\bH1s?\b", "The main heading of a page, shown as its biggest title."),
    ("Headings", r"\bH[2-6]\b|heading level", "Section and sub-section titles on a page, like a table of contents."),
    ("Title tag", r"\btitle\(s\)|title tag|<title>|duplicated title","The page title Google shows as the blue headline in search results."),
    ("Meta description", r"meta description","The short text Google may show under the title in "
                                                               "search results."),
    ("Open Graph", r"open graph|\bog:", "Tags that set the title, text and picture shown when a page is shared on "
                                        "social media or WhatsApp."),
    ("Structured data", r"json-ld|structured data|schema", "Hidden code that describes the business, products or "
                                                            "offers to search engines in a standard format."),
    ("sameAs", r"\bsameas\b", "A line in the structured data that lists the business's official profiles."),
    ("Rich results", r"rich result", "Special search displays such as star ratings, prices or FAQs."),
    ("SERP", r"\bSERPs?\b|search results page", "Search engine results page: what Google shows for a search."),
    ("Featured snippet", r"featured snippet", "The highlighted answer box at the top of some Google results."),
    ("People Also Ask", r"people also ask|\bPAA\b", "Google's box of related questions people search for."),
    ("AI Overview", r"ai overview", "The AI-written answer Google shows above the normal results for some "
                                    "searches."),
    ("Knowledge panel", r"knowledge (graph|panel)", "The information box Google shows about a business or "
                                                    "organisation."),
    ("Wikidata", r"wikidata", "A free database of facts about organisations that AI systems learn from."),
    ("Google Business Profile", r"business profile|google maps|\bmaps listing", "The business's listing on "
                                                                                "Google Maps and Search."),
    ("NAP", r"\bNAP\b", "Name, address and phone number of the business."),
    ("llms.txt", r"llms\.txt", "An optional file that summarises a site for AI tools."),
    ("Lazy-loading", r"lazy", "Loading pictures only when they are about to come into view."),
    ("Render-blocking", r"render-blocking|blocks? render", "Code that must finish loading before anything on the "
                                                           "page can appear."),
    ("JavaScript", r"javascript|\bJS\b", "Code that runs in the browser to add content or interactivity."),
    ("Server-side rendering", r"\bSSR\b|server-render|pre-render", "Sending a page's full content from the server, "
                                                                   "so nothing depends on code running first."),
    ("Crawler", r"crawler|user agent|\bbot\b", "A program that reads websites for a search engine or AI service."),
    ("Anchor text", r"anchor", "The clickable words of a link."),
    ("Viewport", r"viewport", "The setting that makes a page fit a phone screen."),
    ("CDN", r"\bCDN\b", "Content delivery network: servers around the country that deliver pages faster."),
    ("tel: link", r"\btel:", "A phone number visitors can tap to call."),
    ("PIN code", r"\bPIN\b", "India's six-digit postal code."),
    ("Cannibalization", r"cannibali", "When several pages of one site compete for the same search."),
)
_GLOSSARY = [(label, re.compile(pattern, re.I), meaning) for label, pattern, meaning in GLOSSARY]
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_PATH = re.compile(r"(?<![\w.])/[\w\-/.%~]+")
# Technical shorthand a plain sentence must not use (allowed only inside brackets, after an explanation).
_JARGON = re.compile(r"\b(INP|LCP|CLS|TTFB|TBT|JSON-LD|SERP|PAA|CDN|SSR|H1|H2|H3|noindex|canonical|schema|"
                     r"og:\w+|robots\.txt)\b", re.I)
MAX_CASES = 60


def entry(check_id: str) -> Plain | None:
    return LIBRARY.get(check_id)


def library_json() -> dict[str, dict]:
    """The whole library, for the web app (served with the agent catalog)."""
    return {check_id: asdict(p) for check_id, p in LIBRARY.items()}


def terms_in(*texts: str) -> list[dict]:
    text = " ".join(t for t in texts if t)
    return [{"term": label, "meaning": meaning} for label, pattern, meaning in _GLOSSARY if pattern.search(text)]


def _path(url: str) -> str:
    parts = urlsplit(url)
    return (parts.path or "/") if parts.path not in ("", "/") else parts.netloc or url


def issue_key(finding: dict | Finding) -> str:
    """A finding's stable key across the report, the issue cards and the stored site cases."""
    if isinstance(finding, Finding):
        return finding.fingerprint
    scope, locator = finding.get("scope") or {}, finding.get("locator") or {}
    return fingerprint_of(finding["check_id"], scope.get("pages", []), scope.get("template_id"), locator.get("css"))


def fallback_case(finding: dict) -> str:
    """A factual sentence built from the finding itself, used when no model sentence passed validation."""
    pages = [_path(p) for p in (finding.get("scope") or {}).get("pages", [])]
    where = (f"on {len(pages)} page{'s' if len(pages) != 1 else ''}, for example {pages[0]}" if pages
             else "across the site")
    excerpt = next((e.get("excerpt", "").strip() for e in finding.get("evidence") or [] if e.get("excerpt")), "")
    return f"We found this {where}." + (f" What we saw: {excerpt}" if excerpt else "")


def explain(finding: dict, case: str | None = None) -> dict:
    """The plain-language view of one finding: the library entry plus the site's own case."""
    item = entry(finding["check_id"])
    technical = " ".join([finding.get("title", ""), finding.get("fix", ""), finding.get("impact", "")] +
                         [e.get("excerpt", "") for e in finding.get("evidence") or []])
    base = asdict(item) if item else {
        "name": finding.get("title", ""), "problem": finding.get("title", ""), "meaning": finding.get("impact", ""),
        "why": "", "analogy": "", "action": finding.get("fix", "")}
    how = fix_steps(finding)
    return {**base, "site_case": case or fallback_case(finding), "case_source": "model" if case else "rules",
            "terms": terms_in(technical, *how["steps"]), **how}


# ----------------------------------------------------------------- per-run site cases (one model call)

class Case(BaseModel):
    id: str
    text: str = ""


class Cases(BaseModel):
    cases: list[Case] = Field(default_factory=list)


def _issue_line(ref: str, finding: dict) -> str:
    item = entry(finding["check_id"])
    pages = [_path(p) for p in (finding.get("scope") or {}).get("pages", [])[:5]]
    evidence = [e.get("excerpt", "") for e in (finding.get("evidence") or [])[:3]]
    return (f"{ref} | topic: {item.name if item else finding['title']} | finding: {finding['title']} | "
            f"pages: {', '.join(pages) or 'site-wide'} | evidence: {' / '.join(evidence)}")


def valid_case(text: str, line: str) -> bool:
    """Kept only if short, free of shorthand, and every number and page path appears in the issue's data."""
    text = text.strip()
    if not text or len(text) > 320:
        return False
    outside_brackets = re.sub(r"\([^)]*\)", "", text)
    if _JARGON.search(outside_brackets):
        return False
    numbers = set(_NUMBER.findall(line))
    if any(n not in numbers for n in _NUMBER.findall(text)):
        return False
    return all(p.rstrip(".,") in line for p in _PATH.findall(text))


def site_cases(llm: LLMClient | None, findings: list[dict | Finding]) -> dict[str, str]:
    """One plain sentence per issue about this site, keyed by issue_key; issues that fail validation are
    left out (they get fallback_case)."""
    payloads = [f if isinstance(f, dict) else f.model_dump(mode="json") for f in findings]
    issues = sorted((f for f in payloads if f["status"] in ("fail", "warn")),
                    key=lambda f: f["status"] != "fail")[:MAX_CASES]
    if llm is None or not issues:
        return {}
    lines = {f"I{n}": (issue_key(f), _issue_line(f"I{n}", f)) for n, f in enumerate(issues, start=1)}
    try:
        result = llm.complete_json(load_prompt("plain.cases", 1), Cases,
                                   issues="\n".join(line for _, line in lines.values()))
    except LLMError:
        return {}
    kept: dict[str, str] = {}
    for case in result.data.cases:
        if case.id in lines:
            key, line = lines[case.id]
            if key not in kept and valid_case(case.text, line):
                kept[key] = case.text.strip()
    return kept
