# 7. Archetype Packs (India, English)

Each pack is a YAML file in `app/rules/`. Agents read only their own pack; nothing here is hard-coded in agent logic. Compliance items are **prompts for the client's compliance team, not legal advice**, and each pack should be reviewed by someone who knows that sector's current rules before launch.

## Detection signals (C3)

| Archetype | Strong signals |
|---|---|
| Hospitality | Room/rate pages, booking engine, check-in/check-out, amenities, `Hotel`/`LodgingBusiness`/`Restaurant` schema, menus |
| Loans | Interest rates, EMI, eligibility, "apply now", NBFC/bank mentions, KYC, loan types |
| Retail | Product listings, cart, prices in ₹, `Product`/`Offer` schema, returns/shipping pages |
| Logistics | Tracking, pickup, courier/freight/warehousing, pin-code serviceability, rate calculators |

Below 0.8 confidence, or when two archetypes score close, the run pauses for the team to choose. Mixed businesses (for example a hotel with a restaurant) get a primary archetype and an optional secondary pack.

## Journey stages

| Stage | Hospitality | Loans | Retail | Logistics |
|---|---|---|---|---|
| Discover | Destination, property overview | Loan types, what is X loan | Categories, brand story | Services, industries served |
| Evaluate | Rooms, amenities, reviews, photos | Rates, fees, eligibility, comparisons | Product details, specs, reviews | Coverage, transit times, pricing |
| Plan | Location, directions, packages, policies | EMI calculator, documents required | Size guides, comparisons, delivery estimates | Quote calculator, packaging rules, prohibited items |
| Book / Apply / Buy / Ship | Booking engine / enquiry | Application form | Cart and checkout | Pickup booking |
| Manage | Modify/cancel booking, contact | Repayment, statements, foreclosure, support | Order tracking, returns, refunds | Tracking, claims, support |

**A3.02 critical tools:** hospitality: booking engine or enquiry form, room rates · loans: eligibility checker, EMI calculator, documents list, rates and charges page · retail: product search, shipping and returns info, order tracking · logistics: serviceability check, rate/quote calculator, tracking page.

## Schema types (S8.03)

| Archetype | Core types | Supporting types |
|---|---|---|
| All | Organization, WebSite, BreadcrumbList | WebPage, Person (authors), ContactPage |
| Hospitality | Hotel or LodgingBusiness (with address, geo, amenityFeature, checkinTime, checkoutTime), Restaurant where relevant | Offer, AggregateRating (only third-party-sourced), ImageObject |
| Loans | FinancialService (Organization/LocalBusiness for branches), LoanOrCredit per loan product (annualPercentageRate, loanTerm, amount) | Offer, Person (reviewers) |
| Retail | Product, Offer (price, priceCurrency INR, availability), MerchantReturnPolicy, OfferShippingDetails | ProductGroup (variants), OnlineStore / Store |
| Logistics | Organization + Service (serviceType, areaServed, provider) | LocalBusiness for branches/hubs |

These types are for entity clarity. Where Google offers no rich result for a type (e.g. LoanOrCredit), reports say so and never promise a SERP feature.

## Critical tools (A3.02)

Each pack lists its tools as `CriticalTool`s in `engine/rules/packs.py`: the journey stage served and the signals that show the tool exists (form-field names, ids, placeholders and framework bindings; link and button text; visible text; JSON-LD properties). Every pack includes a book-stage tool (booking or enquiry, online application, add to cart, pickup booking) so A3.03 can check the path from the entry page to it.

## Trust and disclosure items (S10.05 / S10.06 / S10.08)

| Archetype | Items S10 checks for |
|---|---|
| Hospitality | Cancellation and refund policy, check-in/check-out times, house rules, taxes and fees shown with prices, contact and address, genuine attributed reviews |
| Loans (YMYL) | Lender identity: RBI registration / NBFC Certificate of Registration number, or names of partner banks/NBFCs where the site is a lending platform. Grievance redressal officer name and contact. Interest rate range / APR and all fees and charges. Fair Practices Code. Key Fact Statement availability. Link to the RBI complaint route. Named authors/reviewers on financial guides. |
| Retail | Legal entity name and address, customer care contact, grievance officer name and contact (e-commerce rules), return/refund/exchange policy, shipping and delivery policy, warranty info, country of origin on product pages, total price including taxes and delivery |
| Logistics | Terms of carriage, liability and claims process, prohibited items, service area and transit times, tracking, contact and grievance route, certifications where held |

In code these are `TrustItem`s in `engine/rules/packs.py` with a `kind` (policy → S10.05, disclosure → S10.06, reviews → S10.07, pricing → S10.08), a `core` flag (absent → fail: cancellation for hotels, returns and grievance officer for retail, RBI registration and grievance officer for loans, terms of carriage for logistics) and the C4 fact keys that carry them. Contact details are S10.02 for every archetype, named authors/reviewers S10.03, tracking an A3 critical tool; certifications aren't checked yet.

## Off-site platforms (G6.03)

| Archetype | Core platforms to check |
|---|---|
| All | Google Maps listing, LinkedIn company page, Knowledge Graph, Wikidata |
| Hospitality | TripAdvisor, MakeMyTrip, Booking.com, Goibibo, Agoda; Zomato/Swiggy for restaurants |
| Loans | Google Play / App Store listing (for app lenders), BankBazaar, Paisabazaar, RBI's list of registered entities (for NBFCs) |
| Retail | Amazon.in, Flipkart, Google Merchant listings, Instagram shop |
| Logistics | IndiaMART, JustDial, TradeIndia, LinkedIn |

## Question-bank and prompt seeds

Each pack ships seed templates, which C7 and C9 label `framework-generated` / `archetype-template`:

- **Hospitality:** "best hotels in {city} near {landmark}", "does {brand} have {amenity}", "{brand} cancellation policy", "check-in time at {brand}"
- **Loans:** "{loan type} interest rate {year}", "documents required for {loan type}", "{brand} loan eligibility", "is {brand} RBI registered", "best {loan type} app in India"
- **Retail:** "{product category} price in India", "{brand} return policy", "is {brand} genuine", "best {category} brands in India"
- **Logistics:** "courier from {city} to {city} charges", "{brand} tracking", "{brand} pickup service areas", "best logistics company for {industry} in India"

## YMYL level

| Archetype | YMYL | Effect |
|---|---|---|
| Loans | High | Severity escalation on S10 and A1.03 accuracy; S4.07 freshness on rates escalates to high; financial drafts require human approval |
| Retail | Medium | Consumer-rule disclosures in S10.06 at high severity |
| Hospitality, Logistics | Standard | Default severities |
