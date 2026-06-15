"""
Style profile persistence for FitFindr.

Stores user style preferences across sessions in a JSON file so outfit
suggestions can reference remembered pieces even when the wardrobe is empty.
"""

import json
import os
import re
import tempfile
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Price/size patterns aligned with agent._parse_query so search terms stay out.
_PRICE_RE = re.compile(
    r"(?:under|below|less than|max|up to|cheaper than)\s*\$?\s*(\d+(?:\.\d+)?)"
    r"|\$\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_SIZE_RE = re.compile(
    r"\bsize\s+([\w/]+)\b|\b(xxs|xs|xl|xxl)\b",
    re.IGNORECASE,
)

_STYLE_CUE_RE = re.compile(
    r"(?:i\s+mostly\s+wear|i\s+usually\s+wear|my\s+style\s+is|i\s+prefer|"
    r"i\s+love\s+wearing|i\s+love|i\s+typically\s+wear)\s+([^.?!]+)",
    re.IGNORECASE,
)


def empty_profile() -> dict:
    """Return a fresh empty style profile dict."""
    return {
        "preference_phrases": [],
        "style_tags": [],
        "colors": [],
        "typical_size": None,
        "interaction_count": 0,
    }


def get_profile_path() -> Path:
    """Profile file path; overridable via FITFINDR_PROFILE_PATH for tests."""
    override = os.environ.get("FITFINDR_PROFILE_PATH")
    if override:
        return Path(override)
    return _DATA_DIR / "style_profile.json"


def profile_has_content(profile: dict | None) -> bool:
    """True when the profile has phrases or tags worth using in styling."""
    if not profile:
        return False
    return bool(profile.get("preference_phrases") or profile.get("style_tags"))


def load_style_profile() -> dict:
    """Load profile from disk; return empty default if missing or invalid."""
    path = get_profile_path()
    if not path.is_file():
        return empty_profile()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return empty_profile()
        base = empty_profile()
        base.update({k: data[k] for k in base if k in data})
        # Normalize list fields.
        for key in ("preference_phrases", "style_tags", "colors"):
            val = base.get(key)
            base[key] = list(val) if isinstance(val, list) else []
        return base
    except (json.JSONDecodeError, OSError):
        return empty_profile()


def save_style_profile(profile: dict) -> None:
    """Atomically write profile JSON to disk."""
    path = get_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _strip_search_tokens(text: str) -> str:
    """Remove price/size tokens so they don't pollute preference extraction."""
    remaining = text or ""
    price_match = _PRICE_RE.search(remaining)
    if price_match:
        remaining = remaining[: price_match.start()] + remaining[price_match.end() :]
    size_match = _SIZE_RE.search(remaining)
    if size_match:
        remaining = remaining[: size_match.start()] + remaining[size_match.end() :]
    return remaining.strip()


def _dedupe_extend(existing: list, new_items: list) -> list:
    """Append unique items, case-insensitive for strings."""
    seen = {str(x).lower() for x in existing}
    out = list(existing)
    for item in new_items:
        key = str(item).lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def extract_preferences_from_query(query: str) -> dict:
    """
    Pull style preference phrases from natural-language query text.

    Returns a partial profile update with preference_phrases and optional typical_size.
    """
    result: dict = {"preference_phrases": [], "typical_size": None}
    if not query or not query.strip():
        return result

    cleaned = _strip_search_tokens(query)

    for match in _STYLE_CUE_RE.finditer(cleaned):
        phrase = match.group(1).strip(" ,.-")
        if phrase:
            # Split "baggy jeans and chunky sneakers" into separate phrases.
            parts = re.split(r"\s+and\s+|\s*,\s*", phrase, flags=re.IGNORECASE)
            for part in parts:
                part = part.strip()
                if part and len(part) > 2:
                    result["preference_phrases"].append(part)

    size_match = _SIZE_RE.search(query)
    if size_match:
        result["typical_size"] = (size_match.group(1) or size_match.group(2)).strip()

    return result


def merge_item_into_profile(profile: dict, item: dict | None) -> dict:
    """Merge style_tags and colors from a selected listing into the profile."""
    if not item or not isinstance(item, dict):
        return profile

    profile["style_tags"] = _dedupe_extend(
        profile.get("style_tags", []),
        item.get("style_tags") or [],
    )
    profile["colors"] = _dedupe_extend(
        profile.get("colors", []),
        item.get("colors") or [],
    )
    return profile


def merge_query_into_profile(profile: dict, query: str) -> dict:
    """Merge regex-extracted preferences from a query into the profile."""
    extracted = extract_preferences_from_query(query)
    profile["preference_phrases"] = _dedupe_extend(
        profile.get("preference_phrases", []),
        extracted.get("preference_phrases", []),
    )
    if extracted.get("typical_size"):
        profile["typical_size"] = extracted["typical_size"]
    return profile


def update_style_profile(query: str, selected_item: dict | None) -> str:
    """
    Load, merge query + item learnings, save, and return a human summary.

    Never raises.
    """
    try:
        profile = load_style_profile()
        before_phrases = list(profile.get("preference_phrases", []))
        before_tags = list(profile.get("style_tags", []))

        if query and query.strip():
            profile = merge_query_into_profile(profile, query)
        if selected_item:
            profile = merge_item_into_profile(profile, selected_item)

        profile["interaction_count"] = profile.get("interaction_count", 0) + 1
        save_style_profile(profile)

        new_phrases = [
            p for p in profile.get("preference_phrases", []) if p not in before_phrases
        ]
        new_tags = [
            t for t in profile.get("style_tags", []) if t not in before_tags
        ]

        parts = []
        if new_phrases:
            parts.append(f"phrases: {', '.join(new_phrases)}")
        elif profile.get("preference_phrases"):
            parts.append(
                f"phrases on file: {', '.join(profile['preference_phrases'][:4])}"
            )
        if new_tags:
            parts.append(f"tags: {', '.join(new_tags)}")
        elif profile.get("style_tags"):
            parts.append(f"tags on file: {', '.join(profile['style_tags'][:4])}")

        if parts:
            return f"Remembered — {'; '.join(parts)}."
        if not query and not selected_item:
            return (
                "No new style preferences to remember — pass a query or "
                "selected listing to update the profile."
            )
        return "Style profile updated (no new unique preferences this run)."
    except Exception as exc:
        return f"Couldn't update style profile ({exc}). Preferences were not saved."


def format_profile_summary(profile: dict | None) -> str:
    """One-line summary of remembered preferences for the UI."""
    if not profile_has_content(profile):
        return ""
    phrases = profile.get("preference_phrases", [])[:3]
    tags = profile.get("style_tags", [])[:3]
    bits = []
    if phrases:
        bits.append(", ".join(phrases))
    if tags:
        bits.append(f"tags: {', '.join(tags)}")
    return "; ".join(bits)
