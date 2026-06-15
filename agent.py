"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import math
import re

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    compare_price,
    update_style_profile,
    get_trend_context,
)
from utils.style_profile import load_style_profile


# ── query parsing ───────────────────────────────────────────────────────────────

# A price ceiling phrased as "under $30", "below 40", "max $25", or a bare "$30".
_PRICE_RE = re.compile(
    r"(?:under|below|less than|max|up to|cheaper than)\s*\$?\s*(\d+(?:\.\d+)?)"
    r"|\$\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
# A size phrased as "size M" / "size 8", or a standalone letter size token.
_SIZE_RE = re.compile(
    r"\bsize\s+([\w/]+)\b|\b(xxs|xs|xl|xxl)\b",
    re.IGNORECASE,
)


def _parse_query(query: str) -> dict:
    """
    Pull a price ceiling and size out of a natural-language query with regex;
    whatever text is left over becomes the description keywords.

    Returns a dict shaped {"description": str, "size": str|None, "max_price": float|None}
    — exactly the three arguments search_listings() takes.
    """
    remaining = query or ""

    # max_price — first price-like mention wins.
    max_price = None
    price_match = _PRICE_RE.search(remaining)
    if price_match:
        amount = price_match.group(1) or price_match.group(2)
        max_price = float(amount)
        remaining = remaining[: price_match.start()] + remaining[price_match.end():]

    # size — "size X" token, else a standalone XXS/XS/XL/XXL.
    size = None
    size_match = _SIZE_RE.search(remaining)
    if size_match:
        size = (size_match.group(1) or size_match.group(2)).strip()
        remaining = remaining[: size_match.start()] + remaining[size_match.end():]

    # description — leftover text, collapsed whitespace and trailing fillers.
    description = re.sub(r"\s+", " ", remaining).strip(" ,.-")

    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "price_assessment": None,    # string from compare_price (stretch)
        "trend_context": None,       # string from get_trend_context (stretch)
        "style_profile": {},         # loaded from disk at run start
        "style_profile_update": None,  # summary from update_style_profile
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "search_retry": None,        # note when search succeeded after loosening filters
        "error": None,               # set if the interaction ended early
    }


def _format_retry_note(adjustments: list[str], count: int) -> str:
    """Build a user-facing note explaining which filters were loosened on retry."""
    joined = "; ".join(adjustments)
    listing_word = "listing" if count == 1 else "listings"
    return (
        f"No exact matches — retried with {joined} and found {count} {listing_word}."
    )


def _search_with_retry(parsed: dict) -> tuple[list, str | None, list[str]]:
    """
    Search with progressively looser constraints when the initial query returns nothing.

    Loosening order:
      1. Drop size filter (keep description + max_price) if a size was specified.
      2. Raise max_price by 50% (rounded up) if a price ceiling was specified.
      3. Drop both size and price — description-only — if any filter was active.

    Returns (results, retry_note, attempted_adjustments).
    retry_note is a non-empty string on successful retry, else None.
    attempted_adjustments lists every loosening step tried (for exhausted errors).
    """
    desc = parsed["description"]
    orig_size = parsed["size"]
    orig_max = parsed["max_price"]

    results = search_listings(desc, orig_size, orig_max)
    if results:
        return results, None, []

    adjustments: list[str] = []
    size = orig_size
    max_price = orig_max

    # 1. Drop size filter.
    if orig_size:
        results = search_listings(desc, None, max_price)
        size = None
        if results:
            return results, _format_retry_note(
                [f"dropped size filter (was {orig_size})"], len(results)
            ), adjustments
        adjustments.append(f"dropped size filter (was {orig_size})")

    # 2. Raise price ceiling by 50% (rounded up).
    if orig_max is not None:
        raised = math.ceil(orig_max * 1.5)
        results = search_listings(desc, size, raised)
        if results:
            step = f"raised price ceiling to ${raised:.0f} (was ${orig_max:.0f})"
            note_parts = adjustments + [step] if adjustments else [step]
            return results, _format_retry_note(note_parts, len(results)), adjustments
        adjustments.append(
            f"raised price ceiling to ${raised:.0f} (was ${orig_max:.0f})"
        )

    # 3. Description-only search (last resort when any filter was active).
    if orig_size is not None or orig_max is not None:
        results = search_listings(desc, None, None)
        if results:
            step = "removed all filters (description-only search)"
            note_parts = adjustments + [step] if adjustments else [step]
            return results, _format_retry_note(note_parts, len(results)), adjustments
        adjustments.append("removed all filters (description-only search)")

    return [], None, adjustments


def _no_results_error(parsed: dict, retry_attempts: list[str]) -> str:
    """Build an actionable error when search and all retries returned nothing."""
    bits = [f"'{parsed['description']}'"] if parsed["description"] else []
    if parsed["max_price"] is not None:
        bits.append(f"under ${parsed['max_price']:.0f}")
    if parsed["size"]:
        bits.append(f"in size {parsed['size']}")
    criteria = " ".join(bits) if bits else "that query"

    if retry_attempts:
        tried = ", ".join(retry_attempts)
        return (
            f"No listings matched {criteria}. Retried with loosened constraints "
            f"({tried}) but still found nothing. Try using different keywords."
        )

    fixes = []
    if parsed["max_price"] is not None:
        fixes.append("raising your price")
    if parsed["size"]:
        fixes.append("dropping the size filter")
    fixes.append("using different keywords")
    return f"No listings matched {criteria}. Try {', or '.join(fixes)}."


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this run.
    session = _new_session(query, wardrobe)

    # Step 1b: load remembered style preferences from prior sessions.
    session["style_profile"] = load_style_profile()

    # Step 2: parse the query into search arguments.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: search with automatic retry on empty results, then BRANCH.
    results, retry_note, retry_attempts = _search_with_retry(parsed)
    session["search_results"] = results
    session["search_retry"] = retry_note

    if not session["search_results"]:
        # No-results path after retries exhausted: error and STOP here.
        session["error"] = _no_results_error(parsed, retry_attempts)
        return session

    # Step 4: happy path — take the top-ranked listing as the selection.
    session["selected_item"] = session["search_results"][0]

    # Step 4b: assess price against comparable listings in the dataset.
    session["price_assessment"] = compare_price(session["selected_item"])

    # Step 4c: derive marketplace trend context (optionally scoped to parsed size).
    session["trend_context"] = get_trend_context(parsed.get("size"))

    # Step 5: style the selected item against the wardrobe and saved profile.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"],
        session["wardrobe"],
        style_profile=session["style_profile"],
        trend_context=session["trend_context"],
    )

    # Step 6: turn the outfit into a shareable fit card.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: persist learned preferences for future sessions.
    session["style_profile_update"] = update_style_profile(
        query, session["selected_item"]
    )

    # Step 8: done.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe
    from utils.style_profile import empty_profile, get_profile_path, save_style_profile

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nPrice: {session['price_assessment']}")
        print(f"\nTrends: {session['trend_context']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")
        print(f"\nStyle memory: {session['style_profile_update']}")

    print("\n\n=== No-results path (retries exhausted) ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")

    print("\n\n=== Search retry success (size filter dropped) ===\n")
    session_retry = run_agent(
        query="vintage graphic tee size XXS under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session_retry["error"]:
        print(f"Error: {session_retry['error']}")
    else:
        print(f"Search retry note: {session_retry['search_retry']}")
        print(f"Found: {session_retry['selected_item']['title']}")
        print(f"Size on listing: {session_retry['selected_item']['size']}")

    print("\n\n=== Style profile memory: two sessions (empty wardrobe) ===\n")
    demo_profile = get_profile_path().parent / "style_profile_demo.json"
    os.environ["FITFINDR_PROFILE_PATH"] = str(demo_profile)
    save_style_profile(empty_profile())

    print("Session 1 — query includes style cues:\n")
    s1 = run_agent(
        query=(
            "vintage graphic tee under $30. "
            "I mostly wear baggy jeans and chunky sneakers."
        ),
        wardrobe=get_empty_wardrobe(),
    )
    print(f"Found: {s1['selected_item']['title']}")
    print(f"Profile update: {s1['style_profile_update']}")

    print("\nSession 2 — new search, no style re-entry:\n")
    s2 = run_agent(
        query="90s track jacket under $50",
        wardrobe=get_empty_wardrobe(),
    )
    print(f"Found: {s2['selected_item']['title']}")
    print(f"Remembered profile: {s2['style_profile'].get('preference_phrases')}")
    print(f"Outfit (uses memory): {s2['outfit_suggestion'][:200]}...")
    print(f"Profile update: {s2['style_profile_update']}")

    print("\n\n=== Trend awareness demo ===\n")
    from tools import get_trend_context

    print("Trend context (size M):")
    print(get_trend_context("M"))
    session_trend = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    if session_trend["error"]:
        print(f"Error: {session_trend['error']}")
    else:
        print(f"\nTrend context in session: {session_trend['trend_context']}")
        print(f"Outfit (trends in prompt): {session_trend['outfit_suggestion'][:250]}...")
