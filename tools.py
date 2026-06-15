"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
    compare_price(item)                             → str   (stretch)
    update_style_profile(query, selected_item)      → str   (stretch)
    get_trend_context(size)                         → str   (stretch)
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings
from utils.style_profile import profile_has_content, update_style_profile as _persist_style_profile

load_dotenv()

# Groq model used by the two LLM-backed tools.
_MODEL = "llama-3.3-70b-versatile"

# Words that carry no signal for relevance scoring — dropped before matching.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "of", "to", "in", "on",
    "some", "any", "my", "i", "im", "looking", "want", "need", "find",
    "something", "that", "this", "under", "size", "vibe", "kinda", "really",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _keywords(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, and drop stopwords/short tokens."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


def _trend_prompt_block(trend_context: str | None) -> str:
    """Append marketplace trend guidance to an LLM prompt when context is present."""
    if not trend_context or not trend_context.strip():
        return ""
    return (
        "\n\nCurrent thrift trends (from recent marketplace listings):\n"
        f"{trend_context.strip()}\n"
        "Weave at least one of these trends into your suggestion when it fits "
        "the item — name the trend explicitly."
    )


def _display_tag(tag: str) -> str:
    """Format a style tag for human-readable trend output."""
    lowered = tag.lower()
    if lowered in {"y2k", "90s", "70s", "80s"}:
        return lowered.upper() if lowered == "y2k" else lowered
    return tag


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()
    keywords = _keywords(description or "")

    scored = []
    for item in listings:
        # 1. Price filter (inclusive).
        if max_price is not None and item["price"] > max_price:
            continue

        # 2. Size filter — case-insensitive substring so "M" hits "S/M".
        if size is not None:
            if size.strip().lower() not in (item.get("size") or "").lower():
                continue

        # 3. Score by keyword overlap with title + description + style_tags.
        haystack = " ".join(
            [
                item.get("title", ""),
                item.get("description", ""),
                " ".join(item.get("style_tags", [])),
            ]
        ).lower()
        score = sum(1 for kw in keywords if kw in haystack)

        # 4. Drop listings with no keyword relevance (when keywords exist).
        if keywords and score == 0:
            continue

        scored.append((score, item))

    # 5. Sort highest score first; ties keep dataset order (stable sort).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(
    new_item: dict,
    wardrobe: dict,
    style_profile: dict | None = None,
    trend_context: str | None = None,
) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.
        style_profile: Optional saved preferences from prior sessions. When the
                  wardrobe is empty but the profile has content, uses remembered
                  preferences in the prompt instead of generic advice.
        trend_context: Optional trend summary from get_trend_context(); woven
                  into the prompt so suggestions reflect current marketplace trends.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"{new_item.get('title', 'this piece')} "
        f"({new_item.get('category', 'item')}; "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}; "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'}). "
        f"{new_item.get('description', '')}"
    )

    items = wardrobe.get("items", []) if wardrobe else []
    trend_block = _trend_prompt_block(trend_context)

    if not items and profile_has_content(style_profile):
        phrases = ", ".join(style_profile.get("preference_phrases", []))
        tags = ", ".join(style_profile.get("style_tags", []))
        colors = ", ".join(style_profile.get("colors", []))
        prompt = (
            "You are a thrift-savvy personal stylist.\n"
            f"A user just found this secondhand item:\n{item_desc}\n\n"
            "From prior sessions they told you they usually wear: "
            f"{phrases or 'n/a'}\n"
            f"Their saved style tags: {tags or 'n/a'}\n"
            f"Colors they gravitate toward: {colors or 'n/a'}\n\n"
            "Suggest 1-2 complete outfits built around the new item, naming "
            "their remembered pieces and preferences by name. Keep it to 2-4 "
            "sentences, concrete and wearable. Mention a styling tweak if it helps."
            f"{trend_block}"
        )
    elif not items:
        # Empty wardrobe, no saved profile → general styling advice.
        prompt = (
            "You are a thrift-savvy personal stylist.\n"
            f"A user just found this secondhand item:\n{item_desc}\n\n"
            "They haven't told you what's in their closet. Give general styling "
            "advice for this piece in 2-3 sentences: what kinds of pieces pair "
            "well with it, what vibe it suits, and one concrete outfit idea. "
            "Be specific and practical, not a product description."
            f"{trend_block}"
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it.get('name', 'item')} ({it.get('category', '')}; "
            f"{', '.join(it.get('colors', []))}; "
            f"{', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            "You are a thrift-savvy personal stylist.\n"
            f"A user just found this secondhand item:\n{item_desc}\n\n"
            f"Here is what's already in their wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits built around the new item, naming "
            "specific pieces from their wardrobe by name. Keep it to 2-4 "
            "sentences, concrete and wearable. Mention a styling tweak (cuff, "
            "tuck, layer) if it helps."
            f"{trend_block}"
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        suggestion = (response.choices[0].message.content or "").strip()
        if not suggestion:
            raise ValueError("empty completion")
        return suggestion
    except Exception as exc:
        # Never crash the loop — return a usable fallback string.
        return (
            f"Couldn't reach the styling model ({exc}). As a starting point, "
            f"build the look around the {new_item.get('title', 'new piece')} "
            "and pair it with neutral basics and shoes that match its vibe."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # 1. Guard an empty/whitespace-only outfit — return a message, never raise.
    if not outfit or not outfit.strip():
        return (
            "Can't write a fit card without an outfit yet — run suggest_outfit "
            "first so there's a look to caption."
        )

    title = new_item.get("title", "this find")
    price = new_item.get("price")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform", "secondhand")

    prompt = (
        "Write a short, shareable social-media caption (2-4 sentences) for an "
        "outfit-of-the-day post about a thrifted find. Sound like a real person "
        "posting, casual and a little hype — NOT a product description.\n\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        "Mention the item, the price, and the platform once each, naturally. "
        "Capture the vibe of the outfit. Lowercase and an emoji or two are fine."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            # Higher temperature so the caption varies across runs/inputs.
            temperature=1.0,
            max_tokens=200,
        )
        card = (response.choices[0].message.content or "").strip()
        if not card:
            raise ValueError("empty completion")
        return card
    except Exception as exc:
        return (
            f"Couldn't generate a fit card ({exc}). Here's a plain version: "
            f"thrifted the {title} for {price_str} on {platform} — "
            "styling it up and loving it."
        )


# ── Stretch: compare_price ────────────────────────────────────────────────────

def _format_price(amount: float) -> str:
    """Format a dollar amount without trailing .00 when whole."""
    if amount == int(amount):
        return f"${int(amount)}"
    return f"${amount:.2f}"


def _comparable_score(target: dict, candidate: dict) -> int:
    """
    Score how similar two listings are for price comparison.
    Higher = more comparable. Same category is required (score 0 otherwise).
    """
    if target.get("category") != candidate.get("category"):
        return 0

    score = 1  # same category baseline

    target_tags = {t.lower() for t in target.get("style_tags", [])}
    candidate_tags = {t.lower() for t in candidate.get("style_tags", [])}
    score += len(target_tags & candidate_tags) * 2

    if target.get("brand") and target["brand"] == candidate.get("brand"):
        score += 2

    target_words = set(_keywords(target.get("title", "")))
    candidate_words = set(_keywords(candidate.get("title", "")))
    score += len(target_words & candidate_words)

    return score


def compare_price(item: dict) -> str:
    """
    Assess whether a listing's price is fair based on comparable items
    in the mock dataset.

    Args:
        item: A listing dict (usually the selected search result).

    Returns:
        A non-empty string with a price verdict and reasoning that cites
        comparable listings. Never raises.

    Comparables are other listings in the same category, ranked by overlap
    in style_tags, brand, and title keywords. The assessment compares the
    item's price to the median of the top comparables.
    """
    if not item or not isinstance(item, dict):
        return (
            "Can't assess price without a listing to compare. "
            "Run search_listings first and pass the selected item."
        )

    price = item.get("price")
    if not isinstance(price, (int, float)) or price < 0:
        return (
            f"Can't assess price for {item.get('title', 'this item')} — "
            "the listing is missing a valid price."
        )

    title = item.get("title", "this item")
    item_id = item.get("id")

    listings = load_listings()
    scored = []
    for listing in listings:
        if item_id and listing.get("id") == item_id:
            continue
        score = _comparable_score(item, listing)
        if score > 0:
            scored.append((score, listing))

    if not scored:
        return (
            f"No comparable listings in the dataset for {title} "
            f"({_format_price(price)}). Try searching a broader category "
            "or check similar items manually on other platforms."
        )

    scored.sort(key=lambda pair: pair[0], reverse=True)
    # Use the strongest matches; require at least 2 for a median.
    top_comps = [lst for _, lst in scored[:8]]
    if len(top_comps) < 2:
        return (
            f"Only found one comparable for {title} at {_format_price(price)} "
            f"({top_comps[0]['title']} at {_format_price(top_comps[0]['price'])}). "
            "Need at least two similar listings to judge whether the price is fair."
        )

    comp_prices = sorted(lst["price"] for lst in top_comps)
    mid = len(comp_prices) // 2
    if len(comp_prices) % 2:
        median = comp_prices[mid]
    else:
        median = (comp_prices[mid - 1] + comp_prices[mid]) / 2

    low, high = comp_prices[0], comp_prices[-1]
    price_str = _format_price(price)
    median_str = _format_price(median)

    if price <= median * 0.85:
        verdict = "Good deal"
        detail = f"below the typical {_format_price(median)} median"
    elif price <= median * 1.15:
        verdict = "Fair price"
        detail = f"right around the {_format_price(median)} median"
    else:
        verdict = "Above typical"
        detail = f"higher than the {_format_price(median)} median"

    comp_lines = [
        f"{lst['title']} ({_format_price(lst['price'])})"
        for lst in top_comps[:3]
    ]
    comps_text = "; ".join(comp_lines)

    return (
        f"{verdict} — {title} at {price_str} is {detail} for similar "
        f"{item.get('category', 'items')} in this dataset "
        f"(range {_format_price(low)}–{_format_price(high)} across "
        f"{len(top_comps)} comparables). Comps: {comps_text}."
    )


# ── Stretch: update_style_profile ─────────────────────────────────────────────

def update_style_profile(query: str, selected_item: dict | None) -> str:
    """
    Persist style preferences from the query and selected listing to disk.

    Args:
        query: The original user query (regex extracts style cues).
        selected_item: Top search result; style_tags/colors are merged in.

    Returns:
        A non-empty summary string of what was remembered. Never raises.
    """
    return _persist_style_profile(query, selected_item)


# ── Stretch: get_trend_context ────────────────────────────────────────────────

_CATEGORY_VIBES = {
    "tops": "graphic tees and tops",
    "bottoms": "baggy silhouettes and denim",
    "outerwear": "layering pieces and jackets",
    "shoes": "chunky sneakers and boots",
    "accessories": "bags and small accents",
}


def get_trend_context(size: str | None = None) -> str:
    """
    Summarize trending style tags from the mock listings dataset.

    Args:
        size: Optional size filter (loose substring match, same as search).
              None aggregates trends across all listings.

    Returns:
        A non-empty human-readable string naming 3-5 trending tags and a brief
        note about hot categories/platforms. Never raises.
    """
    try:
        listings = load_listings()
    except Exception:
        return (
            "Trend data unavailable — couldn't load the listings dataset. "
            "Try again later or search without a size filter."
        )

    if not listings:
        return (
            "No listing data available to compute current trends. "
            "The mock marketplace dataset is empty."
        )

    if size is not None and size.strip():
        size_key = size.strip()
        filtered = [
            item
            for item in listings
            if size_key.lower() in (item.get("size") or "").lower()
        ]
        size_label = size_key
    else:
        filtered = listings
        size_label = None

    if not filtered:
        return (
            f"No marketplace listings in size {size_label} to derive trends. "
            "Try dropping the size filter or searching a broader size range."
        )

    tag_counts: dict[str, int] = {}
    tag_display: dict[str, str] = {}
    category_counts: dict[str, int] = {}
    platform_counts: dict[str, int] = {}

    for item in filtered:
        for tag in item.get("style_tags", []):
            if not tag or not str(tag).strip():
                continue
            key = str(tag).strip().lower()
            tag_counts[key] = tag_counts.get(key, 0) + 1
            tag_display.setdefault(key, str(tag).strip())

        category = item.get("category") or ""
        if category:
            category_counts[category] = category_counts.get(category, 0) + 1

        platform = item.get("platform") or ""
        if platform:
            platform_counts[platform] = platform_counts.get(platform, 0) + 1

    if not tag_counts:
        if size_label:
            return (
                f"Listings in size {size_label} have no style tags to analyze. "
                "Trend context is limited for this size in the mock dataset."
            )
        return (
            "Listings in the dataset have no style tags to analyze. "
            "Trend context is unavailable."
        )

    ranked_tags = sorted(
        tag_counts.items(),
        key=lambda pair: (-pair[1], pair[0]),
    )
    top_count = min(5, max(3, len(ranked_tags)))
    top_tags = [_display_tag(tag_display[key]) for key, _ in ranked_tags[:top_count]]
    tags_text = ", ".join(top_tags)

    top_categories = sorted(
        category_counts.items(),
        key=lambda pair: (-pair[1], pair[0]),
    )[:2]
    category_bits = [
        _CATEGORY_VIBES.get(cat, f"{cat} pieces") for cat, _ in top_categories
    ]
    vibe_note = " and ".join(category_bits) if category_bits else "mixed categories"

    top_platform = (
        max(platform_counts.items(), key=lambda pair: pair[1])[0]
        if platform_counts
        else "secondhand apps"
    )

    if size_label:
        return (
            f"Trending in size {size_label} right now: {tags_text} — "
            f"lots of {vibe_note} on {top_platform}."
        )

    return (
        f"Trending across the mock marketplace right now: {tags_text} — "
        f"lots of {vibe_note} on {top_platform}."
    )
