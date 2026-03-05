"""Quick smoke test for journal module."""
from cryptoscope_crew.journal import validate_narrative_scan, save_task_output
import tempfile, os, json

d = tempfile.mkdtemp()

# --- Test 1: valid JSON embedded in prose
raw = 'Voici: ' + json.dumps({
    "narratives": [{
        "title": "DeFi Boom",
        "summary": "Explosion DeFi",
        "tickers": ["ETH"],
        "heat": 4,
        "sources": ["https://example.com"]
    }]
}) + ' fin du texte.'

result = validate_narrative_scan(raw, d)
assert len(result["narratives"]) == 1, f"Expected 1 narrative, got {result}"
assert os.path.isfile(os.path.join(d, "narrative_scan.json"))
print("Test 1 PASS: valid JSON extracted and validated")

# --- Test 2: no JSON at all
d2 = tempfile.mkdtemp()
result2 = validate_narrative_scan("pas de json ici", d2)
assert result2 == {"narratives": []}, f"Expected empty fallback, got {result2}"
assert os.path.isfile(os.path.join(d2, "narrative_scan.invalid.txt"))
print("Test 2 PASS: invalid input → fallback + .invalid.txt")

# --- Test 3: heat out of range
d3 = tempfile.mkdtemp()
raw3 = json.dumps({"narratives": [{"title":"x","summary":"s","tickers":[],"heat":0,"sources":[]}]})
result3 = validate_narrative_scan(raw3, d3)
assert result3 == {"narratives": []}, f"Expected fallback for heat=0, got {result3}"
print("Test 3 PASS: heat=0 rejected → fallback")

# --- Test 4: save_task_output
d4 = tempfile.mkdtemp()
p = save_task_output("scan_market", "raw output text", d4)
assert os.path.isfile(p)
print("Test 4 PASS: save_task_output wrote file")

print("\nAll tests passed!")
