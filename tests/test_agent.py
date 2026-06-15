"""
Agent-level tests for the planning loop and retry-with-fallback stretch.

Retry behavior is deterministic (pure search_listings); LLM tools are mocked
so these tests run without GROQ_API_KEY.
"""

from unittest.mock import patch

import pytest

from agent import (
    _no_results_error,
    _parse_query,
    _search_with_retry,
    run_agent,
)
from utils.data_loader import get_example_wardrobe


@pytest.fixture
def mock_llm_tools():
    """Avoid Groq and disk side effects in full run_agent retry tests."""
    with (
        patch("agent.suggest_outfit", return_value="Mock outfit suggestion.") as so,
        patch("agent.create_fit_card", return_value="Mock fit card.") as fc,
        patch("agent.update_style_profile", return_value="Mock profile update.") as up,
    ):
        yield {"suggest_outfit": so, "create_fit_card": fc, "update_style_profile": up}


@pytest.fixture
def profile_path(tmp_path, monkeypatch):
    path = tmp_path / "style_profile.json"
    monkeypatch.setenv("FITFINDR_PROFILE_PATH", str(path))
    return path


# ── _search_with_retry ────────────────────────────────────────────────────────

def test_search_retry_drops_size_filter():
    parsed = _parse_query("vintage graphic tee size XXS under $30")
    results, note, attempts = _search_with_retry(parsed)
    assert len(results) > 0
    assert note is not None
    assert "dropped size filter" in note
    assert "XXS" in note
    assert attempts == []


def test_search_retry_raises_price_ceiling():
    parsed = _parse_query("vintage graphic tee under $11")
    results, note, attempts = _search_with_retry(parsed)
    assert len(results) > 0
    assert note is not None
    assert "raised price ceiling to $17" in note
    assert "was $11" in note
    assert attempts == []


def test_search_retry_exhausted():
    parsed = _parse_query("designer ballgown size XXS under $5")
    results, note, attempts = _search_with_retry(parsed)
    assert results == []
    assert note is None
    assert "dropped size filter" in attempts[0]
    assert "raised price ceiling" in attempts[1]
    assert "removed all filters" in attempts[2]


def test_no_results_error_mentions_retries():
    parsed = _parse_query("designer ballgown size XXS under $5")
    _, _, attempts = _search_with_retry(parsed)
    msg = _no_results_error(parsed, attempts)
    assert "loosened constraints" in msg
    assert "dropped size filter" in msg
    assert "raised price ceiling" in msg
    assert "removed all filters" in msg


# ── run_agent integration ─────────────────────────────────────────────────────

def test_run_agent_retry_success_size(mock_llm_tools, profile_path):
    session = run_agent(
        "vintage graphic tee size XXS under $30",
        get_example_wardrobe(),
    )
    assert session["error"] is None
    assert session["search_retry"]
    assert "dropped size filter" in session["search_retry"]
    assert session["selected_item"] is not None
    assert session["outfit_suggestion"] == "Mock outfit suggestion."
    assert session["fit_card"] == "Mock fit card."


def test_run_agent_retry_success_price(mock_llm_tools, profile_path):
    session = run_agent(
        "vintage graphic tee under $11",
        get_example_wardrobe(),
    )
    assert session["error"] is None
    assert session["search_retry"]
    assert "raised price ceiling" in session["search_retry"]
    assert session["selected_item"] is not None


def test_run_agent_retries_exhausted(mock_llm_tools, profile_path):
    session = run_agent(
        "designer ballgown size XXS under $5",
        get_example_wardrobe(),
    )
    assert session["search_results"] == []
    assert session["search_retry"] is None
    assert session["error"]
    assert "loosened constraints" in session["error"]
    assert session["selected_item"] is None
    assert session["fit_card"] is None
    mock_llm_tools["suggest_outfit"].assert_not_called()


def test_run_agent_first_try_no_retry_note(mock_llm_tools, profile_path):
    session = run_agent(
        "vintage graphic tee under $30",
        get_example_wardrobe(),
    )
    assert session["error"] is None
    assert session["search_retry"] is None
