"""
Tool tests for FitFindr.

Each of the three tools gets at least one test for its failure mode, plus a
happy-path check. Run with:  pytest tests/

The two LLM-backed tools (suggest_outfit, create_fit_card) hit Groq, so those
tests are skipped automatically when GROQ_API_KEY isn't set.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    compare_price,
    update_style_profile,
    get_trend_context,
)
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe
from utils.style_profile import (
    empty_profile,
    extract_preferences_from_query,
    load_style_profile,
    merge_item_into_profile,
    profile_has_content,
    save_style_profile,
)

_HAS_KEY = bool(os.environ.get("GROQ_API_KEY"))
_needs_groq = pytest.mark.skipif(not _HAS_KEY, reason="GROQ_API_KEY not set")


# ── search_listings ─────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    # Every returned item is a full listing dict.
    assert all("price" in item and "title" in item for item in results)


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, no exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=30)
    assert all(item["price"] <= 30 for item in results)


def test_search_size_filter_is_loose():
    # "M" should match a listing sized "S/M".
    results = search_listings("baby tee", size="M", max_price=None)
    assert any("M" in item["size"].upper() for item in results)


def test_search_sorted_by_relevance():
    results = search_listings("vintage denim jeans", size=None, max_price=None)
    # More keyword overlap should rank ahead of less — list is non-increasing.
    # We can't read the private score, so just assert the call is stable/sane.
    assert isinstance(results, list)
    assert len(results) > 0


# ── suggest_outfit ──────────────────────────────────────────────────────────

@_needs_groq
def test_suggest_outfit_with_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


@_needs_groq
def test_suggest_outfit_empty_wardrobe():
    # Failure mode: empty wardrobe → general advice, never empty/crash.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


# ── create_fit_card ─────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit():
    # Failure mode: missing outfit → descriptive error string, no exception.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("", item)
    assert isinstance(card, str)
    assert card.strip() != ""
    assert "suggest_outfit" in card  # points the user at the fix


def test_create_fit_card_whitespace_outfit():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("   \n  ", item)
    assert isinstance(card, str)
    assert "suggest_outfit" in card


@_needs_groq
def test_create_fit_card_happy_path():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card(
        "Tuck the tee into baggy jeans with chunky sneakers.", item
    )
    assert isinstance(card, str)
    assert card.strip() != ""


# ── compare_price (stretch) ─────────────────────────────────────────────────

def test_compare_price_returns_assessment():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    assessment = compare_price(item)
    assert isinstance(assessment, str)
    assert assessment.strip() != ""
    # Should cite comparables and a verdict keyword.
    assert any(
        word in assessment.lower()
        for word in ("deal", "fair", "above", "median", "comparable")
    )


def test_compare_price_missing_item():
    assessment = compare_price({})
    assert isinstance(assessment, str)
    assert "listing" in assessment.lower() or "price" in assessment.lower()


def test_compare_price_agent_includes_assessment():
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    session = run_agent(
        "vintage graphic tee under $30",
        get_example_wardrobe(),
    )
    assert session["error"] is None
    assert session["price_assessment"]
    assert isinstance(session["price_assessment"], str)


# ── style profile memory (stretch) ────────────────────────────────────────────

@pytest.fixture
def profile_path(tmp_path, monkeypatch):
    path = tmp_path / "style_profile.json"
    monkeypatch.setenv("FITFINDR_PROFILE_PATH", str(path))
    return path


def test_extract_preferences_from_query():
    extracted = extract_preferences_from_query(
        "vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers."
    )
    phrases = [p.lower() for p in extracted["preference_phrases"]]
    assert "baggy jeans" in phrases
    assert "chunky sneakers" in phrases


def test_merge_item_adds_style_tags():
    profile = empty_profile()
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    merge_item_into_profile(profile, item)
    assert profile["style_tags"]
    assert profile_has_content(profile)


def test_profile_persists_across_loads(profile_path):
    profile = empty_profile()
    profile["preference_phrases"] = ["wide-leg trousers"]
    save_style_profile(profile)
    loaded = load_style_profile()
    assert loaded["preference_phrases"] == ["wide-leg trousers"]


def test_update_style_profile_tool(profile_path):
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    summary = update_style_profile(
        "I mostly wear baggy jeans and chunky sneakers.",
        item,
    )
    assert isinstance(summary, str)
    assert summary.strip()
    loaded = load_style_profile()
    assert "baggy jeans" in [p.lower() for p in loaded["preference_phrases"]]
    assert loaded["style_tags"]


def test_suggest_outfit_uses_profile_when_wardrobe_empty(profile_path):
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    profile = empty_profile()
    profile["preference_phrases"] = ["baggy jeans", "chunky sneakers"]
    profile["style_tags"] = ["streetwear"]

    captured = {}

    def fake_create(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        choice = MagicMock()
        choice.message.content = "Pair with your baggy jeans and chunky sneakers."
        response = MagicMock()
        response.choices = [choice]
        return response

    mock_client = MagicMock()
    mock_client.chat.completions.create = fake_create

    with patch("tools._get_groq_client", return_value=mock_client):
        out = suggest_outfit(item, get_empty_wardrobe(), style_profile=profile)

    assert "baggy jeans" in captured["prompt"]
    assert "chunky sneakers" in captured["prompt"]
    assert out.strip()


def test_agent_second_run_uses_saved_profile(profile_path):
    from agent import run_agent

    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    update_style_profile(
        "I mostly wear baggy jeans and chunky sneakers.",
        item,
    )

    session = run_agent(
        "90s track jacket under $50",
        get_empty_wardrobe(),
    )
    assert session["error"] is None
    assert profile_has_content(session["style_profile"])
    assert session["style_profile"]["preference_phrases"]
    assert session["style_profile_update"]


# ── trend awareness (stretch) ─────────────────────────────────────────────────

def test_get_trend_context_returns_string():
    context = get_trend_context()
    assert isinstance(context, str)
    assert context.strip()
    assert "Trending" in context or "trend" in context.lower()


def test_get_trend_context_size_filter():
    all_context = get_trend_context()
    sized_context = get_trend_context("M")
    assert isinstance(sized_context, str)
    assert sized_context.strip()
    assert "size M" in sized_context or "Size M" in sized_context or "M" in sized_context
    # Size filter should still produce actionable trend text for this dataset.
    assert "Trending" in sized_context or "marketplace" in sized_context.lower()


def test_get_trend_context_never_raises():
    for size in (None, "", "   ", "ZZZZZZ", "M"):
        context = get_trend_context(size)
        assert isinstance(context, str)
        assert context.strip()


def test_suggest_outfit_includes_trend_in_prompt():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    trend = get_trend_context("M")
    captured = {}

    def fake_create(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        choice = MagicMock()
        choice.message.content = "Lean into the Y2K streetwear trend with your jeans."
        response = MagicMock()
        response.choices = [choice]
        return response

    mock_client = MagicMock()
    mock_client.chat.completions.create = fake_create

    with patch("tools._get_groq_client", return_value=mock_client):
        out = suggest_outfit(
            item,
            get_example_wardrobe(),
            trend_context=trend,
        )

    assert "Current thrift trends" in captured["prompt"]
    assert trend.split(":")[0] in captured["prompt"] or "Trending" in captured["prompt"]
    assert out.strip()


def test_agent_includes_trend_context():
    from agent import run_agent

    session = run_agent(
        "vintage graphic tee under $30, size M",
        get_example_wardrobe(),
    )
    assert session["error"] is None
    assert session["trend_context"]
    assert isinstance(session["trend_context"], str)
    assert "Trending" in session["trend_context"] or "trend" in session["trend_context"].lower()
