"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

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

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

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

    if not items:
        # Empty wardrobe → general styling advice, not a crash.
        prompt = (
            "You are a thrift-savvy personal stylist.\n"
            f"A user just found this secondhand item:\n{item_desc}\n\n"
            "They haven't told you what's in their closet. Give general styling "
            "advice for this piece in 2-3 sentences: what kinds of pieces pair "
            "well with it, what vibe it suits, and one concrete outfit idea. "
            "Be specific and practical, not a product description."
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
