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
Returns an empty list. The agent stops there, sets `session["error"]` to something like *"No listings matched 'designer ballgown' under $5 in size XXS — try raising your price or dropping the size filter,"* and does **not** call `suggest_outfit`.

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

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->

`run_agent()` walks a fixed order but **branches on results** — it doesn't blindly call all three tools.

1. Parse the query into `description` / `size` / `max_price` (regex pulls `$30` / `under 30` for price and a size token; the rest of the query is the description). Store in `session["parsed"]`.
2. Call `search_listings(**parsed)`, store in `session["search_results"]`.
3. **Branch:** if `search_results` is empty → set `session["error"]` to a specific, actionable message and **return early**. `selected_item`, `outfit_suggestion`, and `fit_card` stay `None`.
4. Otherwise set `session["selected_item"] = search_results[0]`.
5. Call `compare_price(selected_item)`, store in `session["price_assessment"]` (informational — does not branch).
6. Call `suggest_outfit(selected_item, wardrobe)`, store in `session["outfit_suggestion"]`.
7. Call `create_fit_card(outfit_suggestion, selected_item)`, store in `session["fit_card"]`.
8. Return the session.

The loop is done when it either hits the early return (error) or fills `fit_card`. The decision that matters is step 3, where empty results take a completely different path than a good search.

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->

Everything lives in one `session` dict created by `_new_session()`. It's the single source of truth for the run. Each tool writes its output back into the session, and the next tool reads from it, so the user never re enters anything:

- `search_listings` → writes `search_results`; the loop copies `search_results[0]` into `selected_item`.
- `compare_price` reads `selected_item` → writes `price_assessment` (shown in the listing panel).
- `suggest_outfit` reads `selected_item` + `wardrobe` → writes `outfit_suggestion`.
- `create_fit_card` reads `outfit_suggestion` + `selected_item` → writes `fit_card`.
- `error` is set only when the loop bails early.

`app.py`'s `handle_query()` reads the final session and maps it to the three UI panels.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Returns `[]`; loop sets `session["error"]` naming what was searched and suggesting a fix ("raise your price / drop the size filter / different keywords"), then stops before `suggest_outfit`. `fit_card` stays `None`. |
| suggest_outfit | Wardrobe is empty | Detects empty `items` and returns general styling advice for the item instead of crashing; the flow continues to the fit card. |
| suggest_outfit | LLM/API call errors (bad key, network, rate limit) | `try/except` catches it and returns a plain fallback string that still names the item, so the loop keeps going. |
| create_fit_card | Outfit input is missing or incomplete | Guards empty/whitespace `outfit` and returns a clear message ("run suggest_outfit first") as a string — no exception, no blank card. |
| create_fit_card | LLM/API call errors | `try/except` returns a plain fallback caption naming the item, price, and platform — no exception. |
| compare_price | Invalid or missing item/price | Returns a message explaining what's missing; loop continues. |
| compare_price | Fewer than two comparables in dataset | Returns a message naming the single comp (if any) and that a median can't be computed; loop continues. |

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

…and through the agent the user sees: *"No listings matched 'designer ballgown' under $5 in size XXS. Try raising your price, or dropping the size filter, or using different keywords."*

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
│  parse query → session["parsed"] = {description, size, max_price}
│        │                                                        │
│        ▼                                                        │
│  search_listings(description, size, max_price)                  │
│        │                                                        │
│        ├── results == []  ──►  session["error"] = "..."  ───────┼──► return early
│        │                                                        │
│        │ results == [item, ...]                                 │
│        ▼                                                        │
│  session["selected_item"] = results[0]                          │
│        │                                                        │
│        ▼                                                        │
│  compare_price(selected_item)  →  session["price_assessment"]   │
│        │                                                        │
│        ▼                                                        │
│  suggest_outfit(selected_item, wardrobe)                        │
│        │   (empty wardrobe → general advice)                    │
│        ▼                                                        │
│  session["outfit_suggestion"] = "..."                           │
│        │                                                        │
│        ▼                                                        │
│  create_fit_card(outfit_suggestion, selected_item)              │
│        │   (empty outfit → error string)                        │
│        ▼                                                        │
│  session["fit_card"] = "..."                                    │
│        │                                                        │
└────────┼────────────────────────────────────────────────────────┘
         ▼
   handle_query() maps session → 3 UI panels
   (listing  |  outfit idea  |  fit card)      error path → error in panel 1 only
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

**Step 3: Suggest outfit.**
- `suggest_outfit(selected_item, example_wardrobe)` runs with the chosen tee and the example closet.
- It returns a suggestion like: *"Tuck the front of the butterfly tee into your baggy straight leg jeans and finish with the chunky white sneakers, then add the black crossbody to keep it light."*
- The loop stores that string in `session["outfit_suggestion"]`.

**Step 4: Fit card.** 
- `create_fit_card(outfit_suggestion, selected_item)` turns the outfit into a caption.
- It might return something like: *"found this y2k butterfly baby tee on depop for $18 and it's already living in my baggy jeans rotation"*
- The loop stores the caption in `session["fit_card"]`.

**Final output to user:**

- The UI shows three panels: the listing details, the outfit idea, and the fit card.
- If the search returns nothing, only the first panel shows, with an error message telling the user what to loosen, such as price or size.
