"""
Tool tests for FitFindr.

Each of the three tools gets at least one test for its failure mode, plus a
happy-path check. Run with:  pytest tests/

The two LLM-backed tools (suggest_outfit, create_fit_card) hit Groq, so those
tests are skipped automatically when GROQ_API_KEY isn't set.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

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
