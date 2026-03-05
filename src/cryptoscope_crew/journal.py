# src/cryptoscope_crew/journal.py
"""Run-journal : sauvegarde les outputs intermédiaires et valide le JSON narrative_scan."""
from __future__ import annotations

import json, os, pathlib, re, traceback
from typing import Any, Dict, Optional

from cryptoscope_crew.domain.schemas import NarrativeScanOutput


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _extract_json_object(raw: str) -> Optional[str]:
    """Extrait le premier objet JSON { … } complet (best-effort, gère les accolades imbriquées)."""
    start = raw.find("{")
    if start == -1:
        return None
    depth, i = 0, start
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        c = raw[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    return None  # pas trouvé de closing brace


def _ensure_dir(run_dir: str) -> None:
    pathlib.Path(run_dir).mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
#  Sauvegarde brute d'un output de task
# --------------------------------------------------------------------------- #

def save_task_output(task_name: str, raw: str, run_dir: str) -> str:
    """Écrit le texte brut d'un task output dans run_dir/<task_name>.txt.

    Retourne le chemin absolu du fichier créé.
    """
    _ensure_dir(run_dir)
    path = os.path.join(run_dir, f"{task_name}.txt")
    pathlib.Path(path).write_text(raw, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
#  Validation narrative_scan
# --------------------------------------------------------------------------- #

def validate_narrative_scan(raw: str, run_dir: str) -> Dict[str, Any]:
    """Valide la sortie narrative_scan via Pydantic.

    Returns:
        dict  – le dictionnaire validé (clé « narratives »).
                En cas d'échec, retourne {"narratives": []} (fallback).

    Side-effects:
        * Écrit ``narrative_scan.json`` (validé) **ou**
          ``narrative_scan.invalid.txt`` (brut) dans *run_dir*.
    """
    _ensure_dir(run_dir)

    # 1. Extraction du bloc JSON
    json_str = _extract_json_object(raw)
    if json_str is None:
        _save_invalid(raw, run_dir, "Aucun objet JSON trouvé dans la sortie.")
        return {"narratives": []}

    # 2. Parse JSON brut
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        _save_invalid(raw, run_dir, f"JSON invalide : {exc}")
        return {"narratives": []}

    # 3. Validation Pydantic
    try:
        validated = NarrativeScanOutput.model_validate(data)
    except Exception as exc:
        _save_invalid(raw, run_dir, f"Validation Pydantic échouée : {exc}")
        return {"narratives": []}

    # 4. Succès → écrire le JSON validé
    out_path = os.path.join(run_dir, "narrative_scan.json")
    pathlib.Path(out_path).write_text(
        validated.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"[OK] narrative_scan valid\u00e9 -> {out_path}")
    return validated.model_dump()


def _save_invalid(raw: str, run_dir: str, reason: str) -> None:
    path = os.path.join(run_dir, "narrative_scan.invalid.txt")
    content = f"# VALIDATION FAILED\n# {reason}\n\n{raw}"
    pathlib.Path(path).write_text(content, encoding="utf-8")
    print(f"[WARN] narrative_scan invalide ({reason}) -> {path}")
