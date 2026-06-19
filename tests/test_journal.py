"""Tests du module journal (sauvegarde des outputs + validation narrative_scan)."""
import json
import os

from cryptoscope_crew.journal import save_task_output, validate_narrative_scan


def test_valid_json_embedded_in_prose(tmp_path):
    raw = 'Voici: ' + json.dumps({
        "narratives": [{
            "title": "DeFi Boom",
            "summary": "Explosion DeFi",
            "tickers": ["ETH"],
            "heat": 4,
            "sources": ["https://example.com/article"]
        }]
    }) + ' fin du texte.'

    result = validate_narrative_scan(raw, str(tmp_path))
    assert len(result["narratives"]) == 1
    assert os.path.isfile(tmp_path / "narrative_scan.json")


def test_no_json_falls_back(tmp_path):
    result = validate_narrative_scan("pas de json ici", str(tmp_path))
    assert result == {"narratives": []}
    assert os.path.isfile(tmp_path / "narrative_scan.invalid.txt")


def test_heat_out_of_range_rejected(tmp_path):
    raw = json.dumps({"narratives": [
        {"title": "x", "summary": "s", "tickers": [], "heat": 0,
         "sources": ["https://example.com/x"]}
    ]})
    result = validate_narrative_scan(raw, str(tmp_path))
    assert result == {"narratives": []}


def test_save_task_output(tmp_path):
    p = save_task_output("scan_market", "raw output text", str(tmp_path))
    assert os.path.isfile(p)
