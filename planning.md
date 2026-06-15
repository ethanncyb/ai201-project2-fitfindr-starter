# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Searches the 40 item mock listings dataset and returns the ones that best match what the user described, optionally filtered by size and price.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->

| Parameter | Type | Description |
|---|---|---|
| `description` | `str` | Keywords for what the user wants, e.g. `"vintage graphic tee"`. Used for relevance scoring. |
| `size` | `str` | `None` | Size to filter by, e.g. `"M"`. Matched loosely (case-insensitive substring) so `"M"` also hits `"S/M"`. `None` = skip the size filter. |
| `max_price` | `float` | `None` | Inclusive price ceiling. `None` = skip the price filter. |

**What it returns:**
<!-- Describe the return value — what fields does a result contain? -->
A `list[dict]` of full listing dicts (each has `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted by relevance score (highest first). Score = how many description keywords show up in the listing's title + description + style_tags. Listings that match the filters but score 0 on keywords are dropped. Returns `[]` when nothing matches — never raises.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->
Returns an empty list. The agent calls `_search_with_retry()` to automatically loosen filters (drop size → raise price 50% → description-only) before giving up. If a retry succeeds, `session["search_retry"]` explains what changed and the happy path continues. If all retries still return `[]`, the loop sets `session["error"]` naming the original criteria and the loosening steps tried, and does **not** call `suggest_outfit`.

---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Takes the item the user is eyeing plus their existing wardrobe and asks the LLM for 1–2 complete outfit ideas built around that item.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->

| Parameter | Type | Description |
|---|---|---|
| `new_item` | `dict` | A listing dict (the thrifted piece), usually `search_results[0]`. |
| `wardrobe` | `dict` | A wardrobe dict shaped `{"items": [...]}`, where each item has `name`, `category`, `colors`, `style_tags`, and optional `notes`. |

**What it returns:**
<!-- Describe the return value -->
A non empty `str`, a short readable outfit suggestion that names specific wardrobe pieces (e.g. *"Pair it with your baggy straight leg jeans and black combat boots…"*). When the wardrobe is empty it returns general styling advice for the item instead (what vibe it suits, what kinds of pieces pair well).

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->
Empty `wardrobe["items"]` is handled directly (general advice, not a crash). If the LLM call itself errors, catch it and return a plain fallback string so the loop keeps going.

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
Turns the chosen item plus the outfit suggestion into a short casual shareable caption, the kind you'd actually post with an OOTD.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->

| Parameter | Type | Description |
|---|---|---|
| `outfit` | `str` | The outfit suggestion string from `suggest_outfit`. |
| `new_item` | `dict` | The listing dict for the thrifted item (used to name the item, price, and platform). |

**What it returns:**
<!-- Describe the return value -->
A `str`, 2–4 sentences, casual and authentic. Mentions the item name, price, and platform once each, and captures the outfit vibe. Uses a higher LLM temperature so it reads differently for different inputs.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->
If `outfit` is empty or whitespace only, return a descriptive error string (e.g. *"Can't write a fit card without an outfit. Run suggest_outfit first."*) instead of raising. LLM errors are caught and returned as a fallback string.

---

### Additional Tools (if any)

### Tool 4: compare_price (stretch)

**What it does:**
Given a selected listing, estimates whether its price is fair by comparing it to similar items in the mock dataset. Pure Python — no LLM.

**Input parameters:**

| Parameter | Type | Description |
|---|---|---|
| `item` | `dict` | A listing dict, usually `session["selected_item"]` after search. |

**What it returns:**
A non-empty `str` with a verdict (`Good deal`, `Fair price`, or `Above typical`), the item's price vs. the median of comparable listings, the price range across comps, and 2–3 named comparable titles with their prices.

**What happens if it fails or returns nothing:**
Invalid/missing item or price → returns a descriptive message string (no exception). Fewer than two comparables → explains that a fair-price judgment isn't possible and names the one match if any. No comparables at all → suggests broadening the search. The agent still continues to `suggest_outfit` — price assessment is informational, not a hard stop.

**How comparables are chosen:**
1. Exclude the target item by `id`.
2. Score every other listing: same `category` required; +2 per shared `style_tag`, +2 for same `brand`, +1 per shared title keyword (stopword-filtered, same as search).
3. Take the top 8 scored listings (need ≥2 for a median).
4. Verdict thresholds vs. median: ≤85% → Good deal; ≤115% → Fair price; else Above typical.

---

### Tool 5: update_style_profile (stretch)

**What it does:**
Persists the user's style preferences across sessions so they don't have to re-describe their wardrobe every time. Uses hybrid extraction: regex cues from the query (`I mostly wear …`, `my style is …`, etc.) plus `style_tags` and `colors` from the selected listing. Pure Python — no LLM.

**Input parameters:**

| Parameter | Type | Description |
|---|---|---|
| `query` | `str` | The original user query for this interaction. |
| `selected_item` | `dict` \| `None` | The top search result; tags/colors are merged into the profile. `None` if nothing was selected. |

**What it returns:**
A non-empty `str` summary of what was remembered (e.g. *"Remembered: baggy jeans, chunky sneakers; tags: streetwear, y2k"*). Never raises.

**What happens if it fails or returns nothing:**
Empty/missing query → still merges listing tags if `selected_item` is valid; returns a message explaining nothing new was extracted from the query. Invalid `selected_item` → extracts from query only. Profile is saved to `data/style_profile.json` (gitignored; template at `data/style_profile.default.json`).

**Storage schema** (`data/style_profile.json`):

```json
{
  "preference_phrases": ["baggy jeans", "chunky sneakers"],
  "style_tags": ["streetwear", "baggy"],
  "colors": [],
  "typical_size": null,
  "interaction_count": 0
}
```

Path overridable via `FITFINDR_PROFILE_PATH` for tests.

---

### Tool 6: get_trend_context (stretch)

**What it does:**
Derives current thrift-market trend signals from the mock listings dataset (aggregated `style_tags`, categories, and platforms) and returns a short human-readable summary. Pure Python — no external API. Optionally scoped to a size when the user's query includes one.

**Input parameters:**

| Parameter | Type | Description |
|---|---|---|
| `size` | `str` \| `None` | Size filter (same loose substring match as `search_listings`, e.g. `"M"` hits `"S/M"`). `None` = trends across all listings. |

**What it returns:**
A non-empty `str` naming 3–5 trending `style_tags` plus a brief note about hot categories/platforms in that size range (e.g. *"Trending in size M right now: Y2K, streetwear, vintage — lots of tops and outerwear on Depop."*). Never raises.

**What happens if it fails or returns nothing:**
Empty dataset, no listings after size filter, or missing tags → returns a descriptive message string explaining what's unavailable and what to try (e.g. drop the size filter). The agent still continues to `suggest_outfit` — trend context is informational, not a hard stop.

**Data source:** `data/listings.json` via `load_listings()`. Tags are counted across listings (optionally size-filtered); top tags by frequency drive the summary. No live Depop/Poshmark API — the mock dataset simulates platform tag data.

---

## Retry Logic with Fallback (stretch)

When the initial `search_listings` call returns `[]`, `_search_with_retry()` in `agent.py` automatically retries with progressively looser constraints **before** setting `session["error"]`.

**Loosening order:**

1. **Drop size filter** — search with `size=None`, keep `description` and `max_price`. Only if the original query had a size.
2. **Raise price ceiling by 50% (rounded up)** — e.g. `$11` → `$17`. Only if the original query had `max_price` and step 1 (if run) still returned nothing. Uses the current size state after step 1 (size stays dropped if step 1 ran).
3. **Drop both size and price** — description-only search (`size=None`, `max_price=None`). Last resort when at least one filter was active in the original query.

**Branch logic:**

- **First-try success:** `search_retry` stays `None`; happy path continues unchanged.
- **Retry success:** store results normally; set `session["search_retry"]` to a non-empty string (e.g. *"No exact matches — retried with dropped size filter (was XXS) and found 20 listings."*); do **not** set `session["error"]`; continue to `compare_price`, `suggest_outfit`, etc.
- **All retries exhausted:** set `session["error"]` mentioning original criteria **and** which loosening steps were tried; leave `outfit_suggestion`, `fit_card`, and `style_profile_update` as `None`.

Retry logic lives in `agent.py` only — `search_listings()` itself is unchanged.

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

`run_agent()` walks a fixed order but **branches on results** — it doesn't blindly call all three tools.

0. Load `style_profile` from `data/style_profile.json` into `session["style_profile"]`.
1. Parse the query into `description` / `size` / `max_price` (regex pulls `$30` / `under 30` for price and a size token; the rest of the query is the description). Store in `session["parsed"]`.
2. Call `_search_with_retry(parsed)` (wraps `search_listings` with automatic loosening), store results in `session["search_results"]` and any note in `session["search_retry"]`.
3. **Branch:** if `search_results` is still empty after all retries → set `session["error"]` (mentions retries attempted) and **return early**. `selected_item`, `outfit_suggestion`, and `fit_card` stay `None`. Profile is **not** updated.
4. Otherwise set `session["selected_item"] = search_results[0]`. If `search_retry` is set, the UI prepends it to the listing panel.
5. Call `compare_price(selected_item)`, store in `session["price_assessment"]` (informational — does not branch).
6. Call `get_trend_context(parsed["size"])`, store in `session["trend_context"]` (informational — does not branch).
7. Call `suggest_outfit(selected_item, wardrobe, style_profile=session["style_profile"], trend_context=session["trend_context"])`, store in `session["outfit_suggestion"]`. Trend context is woven into the LLM prompt when present so suggestions reflect what's hot in the marketplace.
8. Call `create_fit_card(outfit_suggestion, selected_item)`, store in `session["fit_card"]`.
9. Call `update_style_profile(query, selected_item)`, store summary in `session["style_profile_update"]` and persist to disk.
10. Return the session.

The loop is done when it either hits the early return (error) or fills `fit_card`. The decision that matters is step 3, where empty results after retries take a completely different path than a good search (including a successful retry).

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

Everything lives in one `session` dict created by `_new_session()`. It's the single source of truth for the run. Each tool writes its output back into the session, and the next tool reads from it, so the user never re enters anything:

- `load_style_profile()` → `session["style_profile"]` at run start (read from `data/style_profile.json`).
- `_search_with_retry(parsed)` → writes `search_results` and optionally `search_retry` (user-facing note when filters were loosened); the loop copies `search_results[0]` into `selected_item`.
- `compare_price` reads `selected_item` → writes `price_assessment` (shown in the listing panel).
- `get_trend_context` reads `parsed["size"]` → writes `trend_context` (shown in the outfit panel; passed into `suggest_outfit`).
- `suggest_outfit` reads `selected_item` + `wardrobe` + `style_profile` + `trend_context` → writes `outfit_suggestion`.
- `create_fit_card` reads `outfit_suggestion` + `selected_item` → writes `fit_card`.
- `update_style_profile` reads `query` + `selected_item` → writes `style_profile_update` and persists to disk.
- `error` is set only when the loop bails early.

`app.py`'s `handle_query()` reads the final session and maps it to the three UI panels, including remembered-style notes in the outfit panel.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Returns `[]`; `_search_with_retry()` loosens filters (drop size → raise price 50% → description-only) and retries. On retry success: `search_retry` explains what changed, happy path continues. If all retries fail: `session["error"]` names original criteria and steps tried, then stops before `suggest_outfit`. `fit_card` stays `None`. |
| suggest_outfit | Wardrobe is empty | Detects empty `items` and returns general styling advice for the item instead of crashing; the flow continues to the fit card. |
| suggest_outfit | LLM/API call errors (bad key, network, rate limit) | `try/except` catches it and returns a plain fallback string that still names the item, so the loop keeps going. |
| create_fit_card | Outfit input is missing or incomplete | Guards empty/whitespace `outfit` and returns a clear message ("run suggest_outfit first") as a string — no exception, no blank card. |
| create_fit_card | LLM/API call errors | `try/except` returns a plain fallback caption naming the item, price, and platform — no exception. |
| compare_price | Invalid or missing item/price | Returns a message explaining what's missing; loop continues. |
| compare_price | Fewer than two comparables in dataset | Returns a message naming the single comp (if any) and that a median can't be computed; loop continues. |
| update_style_profile | Empty query and no selected item | Returns a message that nothing new was saved; no exception. |
| update_style_profile | Disk write failure | Returns a descriptive message string; loop still returns the session with outfit/fit card intact. |
| suggest_outfit | Empty wardrobe but saved style profile | Uses remembered preferences in the LLM prompt instead of generic advice. |
| get_trend_context | No listings match size filter | Returns a message suggesting a broader size search; loop continues with `trend_context` set to that message (LLM may ignore if not actionable). |
| get_trend_context | Listings load but have no style_tags | Returns a descriptive message; loop continues. |

### Triggered-failure example (captured from testing)

The most useful deterministic failure check is the empty-outfit guard in `create_fit_card`. It does not rely on the model or API key, so it is safe to reproduce and document:

```
$ ./.venv/bin/python -c "from tools import create_fit_card; print(create_fit_card('', {'title': 'Faded Band Tee', 'price': 22, 'platform': 'Depop'}))"
Can't write a fit card without an outfit yet — run suggest_outfit first so there's a look to caption.
```

I also verified the no-results branch in `search_listings`:

```
$ ./.venv/bin/python -c "from tools import search_listings; print(search_listings('designer ballgown', size='XXS', max_price=5))"
[]
```

…and through the agent the user sees: *"No listings matched 'designer ballgown' under $5 in size XXS. Retried with loosened constraints (dropped size filter (was XXS), raised price ceiling to $8 (was $5), removed all filters (description-only search)) but still found nothing. Try using different keywords."*

**Retry success example** (`vintage graphic tee size XXS under $30`):

```
$ python -c "from agent import run_agent; from utils.data_loader import get_example_wardrobe; s=run_agent('vintage graphic tee size XXS under \$30', get_example_wardrobe()); print(s['search_retry'])"
No exact matches — retried with dropped size filter (was XXS) and found 20 listings.
```

---

## Architecture

<!-- Draw a diagram of your agent showing how the components connect:
     User input → Planning Loop → Tools (search_listings, suggest_outfit, create_fit_card)
                                                                          ↕
                                                                   State / Session
     Show what triggers each tool, how state flows between them, and where error paths branch off.
     ASCII art, a Mermaid diagram (https://mermaid.js.org/syntax/flowchart.html), or an embedded
     sketch are all fine. You'll share this diagram with an AI tool when asking it to implement
     the planning loop and each individual tool. -->
```
User query  +  wardrobe choice
        │
        ▼
┌─────────────────── Planning Loop (run_agent) ───────────────────┐
│                                                                 │
│  load_style_profile() → session["style_profile"]  ◄── disk      │
│        │                                                        │
│        ▼                                                        │
│  parse query → session["parsed"] = {description, size, max_price}
│        │                                                        │
│        ▼                                                        │
│  _search_with_retry(parsed)  →  search_listings (with retries) │
│        │                                                        │
│        ├── results == [] after all retries                      │
│        │       ──►  session["error"] = "…retried…"  ────────────┼──► return early
│        │                                                        │
│        │ results found (first try or retry)                     │
│        ▼                                                        │
│  session["search_results"]; session["search_retry"] if retried  │
│        │                                                        │
│        ▼                                                        │
│  session["selected_item"] = results[0]                          │
│        │                                                        │
│        ▼                                                        │
│  compare_price(selected_item)  →  session["price_assessment"]   │
│        │                                                        │
│        ▼                                                        │
│  get_trend_context(parsed size)  →  session["trend_context"]    │
│        │                                                        │
│        ▼                                                        │
│  suggest_outfit(..., style_profile, trend_context)              │
│        │   (trends woven into LLM prompt when present)          │
│        ▼                                                        │
│  session["outfit_suggestion"] = "..."                           │
│        │                                                        │
│        ▼                                                        │
│  create_fit_card(outfit_suggestion, selected_item)              │
│        │   (empty outfit → error string)                        │
│        ▼                                                        │
│  session["fit_card"] = "..."                                    │
│        │                                                        │
│        ▼                                                        │
│  update_style_profile(query, selected_item)  ──► disk            │
│        → session["style_profile_update"]                        │
│        │                                                        │
└────────┼────────────────────────────────────────────────────────┘
         ▼
   handle_query() maps session → 3 UI panels
   (listing + search_retry note  |  outfit idea  |  fit card)      error path → error in panel 1 only
```

The `session` dict threads through every box. Each tool reads the prior result from it and writes its own back in.

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

Tool used: **Claude (Claude Code)**, one tool at a time.

- **search_listings:** Gave Claude the Tool 1 block above (inputs, return type, scoring rule, empty-list failure mode) and asked it to implement the function over `load_listings()` — no re-reading the JSON. *Verify:* confirm it filters by all three params (price ceiling, loose case-insensitive size substring, keyword score), drops zero-score items, sorts highest-first, and returns `[]` rather than raising. *Tested with:* `"vintage graphic tee" / None / $30` (expect the Y2K baby tee on top), `"designer ballgown" / XXS / $5` (expect `[]`), and a `max_price=30` jacket query (assert every result ≤ 30).
- **suggest_outfit:** Gave Claude the Tool 2 block and the empty-wardrobe requirement, asked it to build two prompt branches (named wardrobe pieces vs. general advice) and call Groq `llama-3.3-70b-versatile`. *Verify:* empty `wardrobe["items"]` takes the general-advice branch, LLM errors are caught and returned as a fallback string, output is never `""`. *Tested with:* example wardrobe and `get_empty_wardrobe()`.
- **create_fit_card:** Gave Claude the Tool 3 block, asked it to guard empty/whitespace `outfit` with an error string (no exception) and use a higher temperature (1.0) so captions vary. *Verify:* `create_fit_card("", item)` returns a message naming `suggest_outfit`; two runs on the same input produce different text.

What I reviewed/overrode: added a stopword filter to `_keywords()` so filler words ("looking", "under", "size") don't inflate scores, and wrapped both LLM tools in try/except returning fallback strings so a network/model error never breaks the loop. Tests live in `tests/test_tools.py` (≥1 per failure mode); the LLM tests skip automatically when `GROQ_API_KEY` is unset.

**Milestone 4 — Planning loop and state management:**

Tool used: **Claude (Claude Code)**, given the Architecture diagram + the Planning Loop and State Management sections above.

- **run_agent:** Asked Claude to implement the seven-step loop exactly as diagrammed — parse → search → branch on empty results → select top → suggest → fit card → return — writing every intermediate value into the `session` dict. *Verify before trusting:* (a) it branches on `search_results` rather than calling all three tools unconditionally; (b) the no-results path sets `session["error"]` and returns early with `selected_item`/`outfit_suggestion`/`fit_card` all left `None`; (c) `selected_item is search_results[0]` (same object flows on, no re-fetch). All three confirmed from the terminal.
- **Query parsing (documented choice):** regex, not the LLM — `_parse_query()` pulls a price ceiling (`under/below/max $N` or a bare `$N`), then a size (`size X` token, or a standalone `XXS/XS/XL/XXL`), and treats the leftover text as the description. Chose regex because it's deterministic, free, and easy to test; the description keywords are forgiving since `search_listings` does its own stopword filtering and scoring.
- **handle_query (app.py):** Asked Claude to map the returned `session` onto the three panels — guard empty query, pick the wardrobe from the radio, run the agent, route `error` to panel 1 only, else format the listing for panel 1 and pass `outfit_suggestion`/`fit_card` through. Did not touch `build_interface()` or the event wiring.

What I reviewed/overrode: tightened the no-results `error` string so it names the exact criteria searched and the specific fixes (raise price / drop size / different keywords), built from whichever parsed fields were actually present rather than a generic "no results" line.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.
**What FitFindr does:** A casual request like *"vintage graphic tee under $30, size M"* flows through three tools in order:

- `search_listings` finds matching thrift listings.
- `suggest_outfit` styles the top result against the user’s wardrobe.
- `create_fit_card` turns the outfit into a shareable caption.

Each tool depends on the one before it. If search returns nothing, the run stops early and tells the user what to loosen. If the wardrobe is empty, `suggest_outfit` still returns general styling advice. If the outfit is missing, `create_fit_card` returns a clear message instead of crashing.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1: Search.** 
- The loop parses the query into `description="vintage graphic tee"`, `size=None`, and `max_price=30.0`, then calls `search_listings("vintage graphic tee", None, 30.0)`.
- The search returns matching tees sorted by relevance, such as a Y2K butterfly baby tee for $18 on depop.
- The loop stores the full result list in `session["search_results"]` and copies the top item into `session["selected_item"]`.

**Step 2: Price check (stretch).**
- `compare_price(selected_item)` finds similar tops in the dataset (shared category + style tags) and compares the $18 asking price to their median (~$23).
- Returns something like: *"Good deal — Y2K Baby Tee at $18 is below the typical $23 median… Comps: Graphic Tee — 2003 Tour ($24); Vintage Band Tee ($19)."*
- Stored in `session["price_assessment"]` and shown at the bottom of the listing panel.

**Step 3: Trend context (stretch).**
- `get_trend_context("M")` aggregates `style_tags` from size-M listings in `data/listings.json` (e.g. Y2K, streetwear, vintage, graphic tee).
- Returns something like: *"Trending in size M right now: Y2K, streetwear, vintage, graphic tee — lots of tops on Depop."*
- Stored in `session["trend_context"]` and shown at the top of the outfit panel.

**Step 4: Suggest outfit.**
- `suggest_outfit(selected_item, example_wardrobe, trend_context=session["trend_context"])` runs with the chosen tee, the example closet, and the trend summary in the LLM prompt.
- It returns a suggestion like: *"Tuck the front of the butterfly tee into your baggy straight leg jeans and finish with the chunky white sneakers — lean into the Y2K/streetwear vibe that's trending in your size."*
- The loop stores that string in `session["outfit_suggestion"]`.

**Step 5: Fit card.** 
- `create_fit_card(outfit_suggestion, selected_item)` turns the outfit into a caption.
- It might return something like: *"found this y2k butterfly baby tee on depop for $18 and it's already living in my baggy jeans rotation"*
- The loop stores the caption in `session["fit_card"]`.

**Final output to user:**

- The UI shows three panels: the listing details, the outfit idea, and the fit card.
- If the search returns nothing (even after retries), only the first panel shows an error message naming what was tried.
- If a retry succeeded, the listing panel includes a 🔁 search note explaining what filter was loosened.

---

## Retry Example Walkthrough

**Example user query:** *"vintage graphic tee size XXS under $30"*

**Step 1: Initial search.**
- Parsed: `description="vintage graphic tee"`, `size="XXS"`, `max_price=30.0`.
- `search_listings(..., "XXS", 30.0)` → `[]` (no XXS graphic tees in the dataset).

**Step 2: Retry — drop size filter.**
- `_search_with_retry` calls `search_listings(..., None, 30.0)` → 20 matching tees.
- Sets `session["search_retry"]` = *"No exact matches — retried with dropped size filter (was XXS) and found 20 listings."*
- Does **not** set `session["error"]`.

**Step 3: Happy path continues.**
- Top result (e.g. Y2K Baby Tee — Butterfly Print, size S/M, $18) → `selected_item`.
- `compare_price` → price assessment shown in listing panel.
- Listing panel prepends the 🔁 search note before the price check.
- `suggest_outfit` → outfit idea; `create_fit_card` → fit card; `update_style_profile` → saved prefs.

**Contrast — retries exhausted:** *"designer ballgown size XXS under $5"* tries all three loosening steps, still finds nothing, sets `session["error"]` listing each step tried, and stops before styling tools.

---

## Two-Session Style Profile Example

Demonstrates cross-session memory: the second interaction uses preferences from the first without re-entry.

**Session 1 — user query (empty wardrobe):**
*"vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers."*

1. `load_style_profile()` → empty profile (first visit).
2. `search_listings("vintage graphic tee", None, 30.0)` → Y2K baby tee at $18.
3. `compare_price` → Good deal assessment.
4. `suggest_outfit(tee, empty_wardrobe, style_profile={})` → general advice (no saved prefs yet this run).
5. `create_fit_card` → shareable caption.
6. `update_style_profile(query, tee)` → saves *"baggy jeans"*, *"chunky sneakers"*, plus tee's `style_tags` to `data/style_profile.json`.

**Session 2 — user query (same empty wardrobe, no style mention):**
*"90s track jacket under $50"*

1. `load_style_profile()` → profile now has *baggy jeans*, *chunky sneakers*, saved tags.
2. `search_listings("90s track jacket", None, 50.0)` → matching jacket.
3. `compare_price` → price assessment.
4. `suggest_outfit(jacket, empty_wardrobe, style_profile=loaded)` → **remembered-style branch**: outfit names baggy jeans and chunky sneakers from the saved profile.
5. `create_fit_card` → caption referencing the jacket + outfit.
6. `update_style_profile` → merges jacket tags into profile.

**What the user sees:** Session 2 outfit panel starts with *"Using remembered style: baggy jeans, chunky sneakers…"* even though they only typed a jacket search.
