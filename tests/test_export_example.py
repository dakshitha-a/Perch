"""scripts/export_example.py: assembly into the replay shape and the name and canary gates.
All text here is SYNTHETIC; the names are invented."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("export_example", ROOT / "scripts/export_example.py")
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

NAMES = {"Zofia Quellmark": "PI-1"}  # SYNTHETIC, invented


def raw_researcher(summary: str = "SYNTHETIC work on lattices.") -> dict:
    lead = {
        "id": "L1",
        "route": "A",
        "rank": 1,
        "record_id": "grants_gov:X-1",
        "status": "kept",
        "cited_ids": ["W1234567"],
        "explanation": "SYNTHETIC fit.",
        "opportunity": {"title": "T"},
    }
    return {
        "side": "researcher",
        "brief": {
            "brief": {
                "id": "b1",
                "researcher_id": "https://openalex.org/A1",
                "summary": summary,
                "stages": [{"name": "researcher", "detail": "Zofia Quellmark"}],
            },
            "researcher": {},
            "awards": [],
            "papers": {},
            "leads": [lead],
        },
        "records": {
            "https://openalex.org/A1": {
                "kind": "researcher",
                "display_name": "Zofia Quellmark",
                "orcid": "0000-0000-0000-0000",
            },
            "nih:1": {"kind": "award", "pi_names": ["Zofia Quellmark"]},
            "grants_gov:X-1": {"kind": "opportunity", "title": "T"},
        },
        "kept": ["L1"],
        "compare": {"rows": [], "offices": []},
        "handoff": {"subject": "S", "body": "Dr. Quellmark writes."},
        "scout": {"id": "s1", "busy": False, "messages": []},
    }


def test_record_ids_split_needed_and_optional():
    must, may = ex.record_ids(raw_researcher()["brief"])
    assert must == {"grants_gov:X-1"}
    assert "https://openalex.org/W1234567" in may and "https://openalex.org/A1" in may


def test_researcher_assembles_to_the_replay_shape_with_aliases():
    text = ex.finish(ex.assemble(raw_researcher(), NAMES), NAMES)
    d = json.loads(text)
    assert {"brief", "records", "candidates", "kept", "compare", "handoffs", "scout"} <= set(d)
    assert d["brief"]["brief"]["id"] == "b1"
    assert d["handoffs"]["research_development"] == {
        "lead_ids": ["L1"],
        "draft": {"subject": "S", "body": "Dr. PI-1 writes."},
    }
    assert d["scout"]["question"] == ex.QUESTION
    assert d["candidates"][0]["display_name"] == "PI-1" and d["candidates"][0]["orcid"] is None
    assert d["records"]["nih:1"]["pi_names"] == []
    assert "Quellmark" not in text


def test_accented_spelling_is_swapped_and_gate_folds_accents():
    raw = raw_researcher(summary="Work by Zofia Quéllmark.")
    text = ex.finish(ex.assemble(raw, NAMES), NAMES)
    assert "llmark" not in text
    assert ex.names_left("a note on Quéllmark", NAMES) == ["Quellmark"]


def test_a_name_left_fails_the_export(monkeypatch):
    monkeypatch.setattr(ex, "swap_names", lambda body, names: body)
    with pytest.raises(ex.ExportError, match="real names left"):
        ex.finish(ex.assemble(raw_researcher(), NAMES), NAMES)


def test_canary_allowed_in_synthetic_records_only():
    tok = "PERCH-CANARY-TEST-0000"  # SYNTHETIC
    raw = {
        "side": "student",
        "brief": {
            "brief": {"id": "b2", "researcher_id": None, "stages": []},
            "papers": {"user:cv": {"text": tok}},
            "leads": [
                {
                    "id": "L",
                    "route": "S",
                    "rank": 1,
                    "record_id": "sample:sch-1",
                    "record": {"canary": tok, "name": tok},
                    "explanation": "fine",
                }
            ],
        },
        "records": {"sample:sch-1": {"canary": tok, "name": "Invented Fund"}},
        "compare": None,
    }
    ex.finish(ex.assemble(raw, NAMES), NAMES)  # passes
    raw["brief"]["leads"][0]["explanation"] = f"cites {tok}"
    with pytest.raises(ex.ExportError, match="canary"):
        ex.finish(ex.assemble(raw, NAMES), NAMES)


def test_a_public_title_sharing_a_surname_is_kept_but_a_researcher_is_not():
    raw = raw_researcher(summary="Zofia Quellmark applies to the Quellmark-Ash Fund.")
    raw["records"]["grants_gov:X-1"]["title"] = "Quellmark-Ash Fund"  # SYNTHETIC
    d = json.loads(ex.finish(ex.assemble(raw, NAMES), NAMES))
    assert d["records"]["grants_gov:X-1"]["title"] == "Quellmark-Ash Fund"
    assert d["brief"]["brief"]["summary"] == "PI-1 applies to the Quellmark-Ash Fund."
    assert d["candidates"][0]["display_name"] == "PI-1"
