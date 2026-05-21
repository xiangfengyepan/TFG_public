"""Unit tests for the api/models endpoint helpers.

Specifically covers `_ollama_models_with_pulled` which merges the
locally-pulled list (from Ollama's `/api/tags`) with the curated
registry catalog so the topology dropdown can show every model the
user could pick, marking the unpulled ones with `pulled: False`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `api/` importable from the repo root so the test runs under the
# host evomas venv that doesn't have the api package installed.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_pulled_models_come_first_and_unpulled_catalog_fills_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pulled-locally models lead (alphabetical); unpulled catalog
    entries follow in their declared catalog order. Pulled entries
    that ALSO appear in the catalog don't duplicate."""
    # Monkeypatch the router module directly — `api.server` re-exports
    # `_ollama_models_with_pulled` for backward compat, but the actual
    # function lives in `api.routers.topology` and looks up its sibling
    # `_ollama_models` via local scope. Patching the source module is the
    # only way the test substitution actually takes effect.
    from api.routers import topology as api_server
    from api.ollama_catalog import OLLAMA_CATALOG

    # `_ollama_models()` is mocked to return one pulled-only model
    # (not in the catalog) and one pulled model that ALSO appears in
    # the catalog. The merge should keep both as pulled=True and not
    # re-emit the catalog duplicate as pulled=False.
    catalog_first = OLLAMA_CATALOG[0]
    monkeypatch.setattr(
        api_server, "_ollama_models",
        lambda: ["ollama/local-only:1b", catalog_first],
    )

    result = api_server._ollama_models_with_pulled()

    # First two entries: pulled. The local-only model and the catalog
    # duplicate both have pulled=True.
    pulled_section = [m for m in result if m["pulled"]]
    assert len(pulled_section) == 2
    pulled_names = {m["name"] for m in pulled_section}
    assert pulled_names == {"ollama/local-only:1b", catalog_first}

    # Pulled section is sorted alphabetically — pulled section comes
    # first in the output, so checking the first two entries' order is
    # enough.
    assert result[0]["name"] <= result[1]["name"]

    # Unpulled section preserves catalog declaration order, minus the
    # already-pulled entry. The second catalog name should be the first
    # unpulled entry.
    unpulled = [m for m in result if not m["pulled"]]
    assert unpulled[0]["name"] == OLLAMA_CATALOG[1]
    # And the catalog entry that was pulled is NOT in the unpulled list.
    assert all(m["name"] != catalog_first for m in unpulled)


def test_unreachable_ollama_still_returns_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the local Ollama server isn't reachable, `_ollama_models()`
    returns []; the catalog still fully populates the dropdown so the
    user can pick something to pull later."""
    # Monkeypatch the router module directly — `api.server` re-exports
    # `_ollama_models_with_pulled` for backward compat, but the actual
    # function lives in `api.routers.topology` and looks up its sibling
    # `_ollama_models` via local scope. Patching the source module is the
    # only way the test substitution actually takes effect.
    from api.routers import topology as api_server
    from api.ollama_catalog import OLLAMA_CATALOG

    monkeypatch.setattr(api_server, "_ollama_models", lambda: [])

    result = api_server._ollama_models_with_pulled()
    assert len(result) == len(OLLAMA_CATALOG)
    assert all(m["pulled"] is False for m in result)
    # Order matches the catalog's declared order.
    assert [m["name"] for m in result] == list(OLLAMA_CATALOG)
