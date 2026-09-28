"""Archetype packs (docs/spec/07-archetype-packs.md): India, English.

Agents and collectors read these; nothing archetype-specific is hard-coded in
agent logic. Compliance items are prompts for the client's compliance team,
not legal advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ARCHETYPES = ("hospitality", "loans", "retail", "logistics")


@dataclass(frozen=True)
class TrustItem:
    key: str
    label: str
    kind: str  # policy (S10.05) | disclosure (S10.06, compliance review) | reviews (S10.07) | pricing (S10.08)
    core: bool = False  # absent → fail (e.g. cancellation for hotels, grievance officer for lenders)
    facts: tuple[str, ...] = ()  # C4 fact keys that carry this item (e.g. check_in_time)


@dataclass(frozen=True)
class CriticalTool:
    """A tool a customer needs at a journey stage (A3.02), with the signals that show it exists.
    Patterns are case-insensitive regexes: `controls` over input names/ids/placeholders/bindings and
    button text, `links` over link text and URLs, `text` over visible text, `jsonld` over JSON-LD
    property names (information that may exist only as structured data)."""
    key: str
    label: str
    stage: str
    controls: str = ""
    links: str = ""
    text: str = ""
    jsonld: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchetypePack:
    id: str
    detection_terms: tuple[str, ...]
    detection_schema_types: tuple[str, ...]
    fact_keys: tuple[str, ...]
    core_schema_types: tuple[str, ...]
    supporting_schema_types: tuple[str, ...]
    journey: dict[str, str]  # stage → what it means for this archetype
    critical_tools: tuple[CriticalTool, ...]
    trust_items: tuple[TrustItem, ...]
    platforms: tuple[str, ...]
    question_seeds: tuple[str, ...]  # {brand} {city} {service} placeholders
    prompt_seeds: tuple[str, ...]
    ymyl: str = "standard"


COMMON_FACT_KEYS = ("business_name", "brand", "legal_name", "address", "city", "phone", "email",
                    "founded_year", "services", "locations_served", "social_profiles")

PACKS: dict[str, ArchetypePack] = {
    "hospitality": ArchetypePack(
        id="hospitality",
        detection_terms=("hotel", "resort", "rooms", "check-in", "check-out", "stay", "suite", "booking",
                         "amenities", "homestay", "villa", "holiday", "restaurant", "banquet"),
        detection_schema_types=("Hotel", "LodgingBusiness", "Resort", "Restaurant", "BedAndBreakfast"),
        fact_keys=COMMON_FACT_KEYS + ("property_name", "room_count", "room_types", "amenities", "dining",
                                      "check_in_time", "check_out_time", "distance_to_landmark", "star_rating",
                                      "price_from", "cancellation_policy", "event_spaces", "nearby_attractions"),
        core_schema_types=("Hotel", "LodgingBusiness", "Resort"),
        supporting_schema_types=("Organization", "WebSite", "BreadcrumbList", "Offer", "ImageObject", "Restaurant"),
        journey={"discover": "destination and property overview", "evaluate": "rooms, amenities, reviews, photos",
                 "plan": "location, directions, packages, policies", "book": "booking engine or enquiry",
                 "manage": "modify or cancel a booking, contact"},
        critical_tools=(
            CriticalTool("booking", "booking engine or enquiry form", "book",
                         controls=r"check-?in|check-?out|arrival|departure|start-?date|end-?date|check availability|"
                                  r"book now|enquir",
                         links=r"\bbook (now|a holiday|your stay|a room|this room)\b|check availability"),
            # Price guidance, not discounts ("flat Rs. 1000 off"): "from ₹4,500", "₹4,500 per night".
            CriticalTool("rates", "room rates or price guidance", "evaluate",
                         text=r"(from|starting|starts at)\s*(₹|\brs\.?|\binr)\s?\d|"
                              r"(₹|\brs\.?|\binr)\s?\d[\d,]*\s*(/|per|a)\s*(night|room)",
                         jsonld=("priceRange", "price", "lowPrice"))),
        trust_items=(TrustItem("cancellation", "cancellation and refund policy", "policy", core=True,
                               facts=("cancellation_policy",)),
                     TrustItem("check_in_out", "check-in and check-out times", "policy",
                               facts=("check_in_time", "check_out_time")),
                     TrustItem("house_rules", "house rules (e.g. ID, pets, visitors)", "policy", facts=("pet_policy",)),
                     TrustItem("taxes_fees", "taxes and fees shown with prices", "pricing", facts=("price_from",)),
                     TrustItem("guest_reviews", "attributed, dated guest reviews", "reviews")),
        platforms=("tripadvisor.in", "makemytrip.com", "booking.com", "goibibo.com", "agoda.com"),
        question_seeds=("best hotels in {city} near {landmark}", "does {brand} have {amenity}",
                        "{brand} check in time", "{brand} cancellation policy", "hotels near {landmark}"),
        prompt_seeds=("What are the best hotels near {landmark} in {city}?", "Tell me about {brand}.",
                      "Which {city} hotels have a swimming pool with a view of {landmark}?"),
    ),
    "loans": ArchetypePack(
        id="loans",
        detection_terms=("loan", "emi", "interest rate", "nbfc", "apply now", "eligibility", "kyc", "tenure",
                         "processing fee", "credit score", "lender"),
        detection_schema_types=("FinancialService", "LoanOrCredit", "BankOrCreditUnion", "MortgageLoan"),
        fact_keys=COMMON_FACT_KEYS + ("loan_types", "interest_rate_range", "processing_fee", "loan_amount_range",
                                      "tenure_range", "eligibility", "documents_required", "rbi_registration",
                                      "partner_lenders", "grievance_officer"),
        core_schema_types=("FinancialService", "LoanOrCredit"),
        supporting_schema_types=("Organization", "WebSite", "BreadcrumbList", "Offer", "Person"),
        journey={"discover": "loan types", "evaluate": "rates, fees, eligibility", "plan": "EMI, documents",
                 "book": "application", "manage": "repayment, statements, support"},
        critical_tools=(
            CriticalTool("eligibility", "eligibility checker", "evaluate", controls=r"eligib|income|salary",
                         links=r"eligib"),
            CriticalTool("emi", "EMI calculator", "plan", controls=r"\bemi\b|loan ?amount|tenure",
                         links=r"emi calculator", text=r"emi calculator"),
            CriticalTool("documents", "documents list", "plan", links=r"documents",
                         text=r"documents? required|required documents|kyc documents"),
            CriticalTool("rates", "rates and charges page", "evaluate",
                         links=r"rates? (and|&) charges|interest rates?|fees (and|&) charges|schedule of charges",
                         text=r"\d+(\.\d+)?\s?%\s?(p\.?\s?a|per annum)"),
            CriticalTool("apply", "online application", "book", controls=r"apply", links=r"\bapply( now| online)?\b")),
        trust_items=(TrustItem("rbi_registration", "RBI registration number or partner bank/NBFC names",
                               "disclosure", core=True, facts=("rbi_registration", "partner_lenders")),
                     TrustItem("grievance_officer", "grievance redressal officer name and contact", "disclosure",
                               core=True, facts=("grievance_officer",)),
                     TrustItem("fair_practices", "Fair Practices Code", "disclosure"),
                     TrustItem("kfs", "Key Fact Statement for loans", "disclosure"),
                     TrustItem("rbi_complaints", "link to the RBI complaint route (RBI CMS or Ombudsman)", "disclosure"),
                     TrustItem("rates_fees", "interest rate range and all fees and charges", "pricing",
                               facts=("interest_rate_range", "processing_fee"))),
        platforms=("bankbazaar.com", "paisabazaar.com", "play.google.com"),
        question_seeds=("{service} interest rate", "documents required for {service}", "{brand} loan eligibility",
                        "is {brand} rbi registered"),
        prompt_seeds=("What is the best {service} option in {city}?", "Is {brand} a safe lender?",
                      "Tell me about {brand}."),
        ymyl="high",
    ),
    "retail": ArchetypePack(
        id="retail",
        detection_terms=("add to cart", "buy now", "shop", "price", "free delivery", "returns", "size guide",
                         "checkout", "in stock"),
        detection_schema_types=("Product", "Offer", "OnlineStore", "Store", "ProductGroup"),
        fact_keys=COMMON_FACT_KEYS + ("product_categories", "return_policy", "shipping_policy", "delivery_time",
                                      "payment_methods", "store_locations", "grievance_officer"),
        core_schema_types=("Product", "Offer"),
        supporting_schema_types=("Organization", "WebSite", "BreadcrumbList", "MerchantReturnPolicy",
                                 "OfferShippingDetails", "ProductGroup"),
        journey={"discover": "categories, brand story", "evaluate": "product details, reviews",
                 "plan": "size guides, delivery estimates", "book": "cart and checkout",
                 "manage": "order tracking, returns, refunds"},
        critical_tools=(
            CriticalTool("search", "product search", "discover", controls=r"^(q|s|search|query|keyword)$|search"),
            CriticalTool("shipping_returns", "shipping and returns information", "plan",
                         links=r"shipping|delivery|returns?|refund|exchange"),
            CriticalTool("cart", "add to cart and checkout", "book", controls=r"add to (cart|bag)|buy now",
                         links=r"/cart|checkout"),
            CriticalTool("tracking", "order tracking", "manage", controls=r"order ?(id|number)",
                         links=r"track (your )?order|order status")),
        trust_items=(TrustItem("legal_entity", "legal entity name and address", "disclosure", core=True,
                               facts=("legal_name",)),
                     TrustItem("grievance_officer", "grievance officer name and contact", "disclosure", core=True,
                               facts=("grievance_officer",)),
                     TrustItem("country_of_origin", "country of origin on product pages", "disclosure"),
                     TrustItem("returns", "return, refund and exchange policy", "policy", core=True,
                               facts=("return_policy",)),
                     TrustItem("shipping", "shipping and delivery policy", "policy", facts=("shipping_policy",)),
                     TrustItem("warranty", "warranty information", "policy"),
                     TrustItem("total_price", "total price including taxes", "pricing")),
        platforms=("amazon.in", "flipkart.com", "instagram.com"),
        question_seeds=("{brand} return policy", "is {brand} genuine", "{service} price in india"),
        prompt_seeds=("What are the best {service} brands in India?", "Tell me about {brand}."),
        ymyl="medium",
    ),
    "logistics": ArchetypePack(
        id="logistics",
        detection_terms=("courier", "shipment", "tracking", "freight", "logistics", "warehouse", "pickup",
                         "delivery", "consignment", "pin code"),
        detection_schema_types=("ParcelDelivery", "DeliveryEvent", "MovingCompany"),
        fact_keys=COMMON_FACT_KEYS + ("service_types", "coverage_area", "transit_times", "prohibited_items",
                                      "certifications", "claims_process"),
        core_schema_types=("Organization", "Service"),
        supporting_schema_types=("WebSite", "BreadcrumbList", "LocalBusiness"),
        journey={"discover": "services, industries", "evaluate": "coverage, transit times, pricing",
                 "plan": "quote, packaging rules", "book": "pickup booking", "manage": "tracking, claims"},
        critical_tools=(
            CriticalTool("serviceability", "serviceability check", "evaluate", controls=r"pin ?code|zip|serviceab",
                         links=r"serviceab|pin ?code"),
            CriticalTool("quote", "rate or quote calculator", "plan", controls=r"weight|dimension|quote",
                         links=r"get (a )?quote|rate calculator|shipping calculator"),
            CriticalTool("pickup", "pickup booking", "book", controls=r"pickup",
                         links=r"book (a )?pickup|schedule pickup|ship now"),
            CriticalTool("tracking", "tracking page", "manage", controls=r"awb|tracking|consignment|docket",
                         links=r"\btrack")),
        trust_items=(TrustItem("carriage_terms", "terms of carriage", "policy", core=True),
                     TrustItem("claims", "liability and claims process", "policy", facts=("claims_process",)),
                     TrustItem("prohibited_items", "prohibited items", "policy", facts=("prohibited_items",)),
                     TrustItem("service_area", "service area and transit times", "policy",
                               facts=("coverage_area", "transit_times")),
                     TrustItem("grievance_route", "grievance or escalation route", "disclosure"),
                     TrustItem("rates", "shipping rates or how prices are calculated", "pricing")),
        platforms=("indiamart.com", "justdial.com", "tradeindia.com", "linkedin.com"),
        question_seeds=("courier from {city} charges", "{brand} tracking", "{brand} pickup service areas"),
        prompt_seeds=("What is the best logistics company in {city}?", "Tell me about {brand}."),
    ),
}


def pack(archetype: str | None) -> ArchetypePack | None:
    return PACKS.get(archetype or "")


def all_fact_keys() -> dict[str, tuple[str, ...]]:
    return {name: p.fact_keys for name, p in PACKS.items()}


@dataclass
class ArchetypeScore:
    archetype: str
    score: float
    signals: list[str] = field(default_factory=list)
