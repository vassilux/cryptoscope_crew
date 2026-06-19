# Architecture & conventions — CryptoScope

> Doc de **référence vivante** (le « comment ça marche »). Maintenue à la main.
> Pour les **décisions datées** voir [analyses/](../analyses/README.md) ; pour le
> contexte global voir [Claude.md](../Claude.md).
> Origine : consolidation des anciennes notes `.agent/skills/` (01/02/06).

## Carte du repo (où mettre quoi)

Code applicatif sous `src/cryptoscope_crew/` :

| Rôle | Emplacement | Nature |
|------|-------------|--------|
| Orchestration CrewAI | `crew.py`, `main.py` | flux |
| Config agents & tâches | `config/agents.yaml`, `config/tasks.yaml` | déclaratif |
| Logique métier (décision, signaux, portefeuille, régime) | `domain/` (`decision_engine.py`, `signal_engine.py`, `portfolio*.py`, `opportunities.py`, `regime*.py`, `macro_regime.py`, `schemas.py`) | pur, déterministe, testable |
| Calculs techniques | `ta/` (`ema_rsi.py`, `confluence_score.py`, `price_action.py`) | pur, déterministe, testable |
| Gestion du risque | `risk/risk.py` | pur, déterministe, testable |
| Accès marché / exchange (CCXT) | `market/exchange.py` | I/O, retries, rate limits |
| Outils CrewAI custom | `tools/custom_tool.py` | wrappers tool (I/O) |
| Prévision K-line (Kronos) | `forecast/` (`kronos.py` + `kronos_model/`) | observation seulement |
| Précompute / rendu | `reporting/precompute.py` | tables + markdown |
| Journalisation des runs | `journal.py` | observabilité |
| Config / env | `config.py` | settings, env loader |

**À éviter**
- Mélanger I/O (accès exchange dans `market/` / `tools/`) et logique pure (`domain/`,
  `ta/`, `risk/`) dans les mêmes fonctions.
- Mettre des règles « métier » dans les prompts — elles doivent vivre en code (`domain/`).

## Flow d'exécution (run)

Pipeline logique :
1. `scan_market` (researcher) → JSON `{"key_drivers":[...]}`
2. `narrative_scan` (researcher) → JSON strict `{"narratives":[...]}`
3. `tech_review` (technician) → JSON `{"tech_notes":[...]}`
4. `reporting_task` (reporting_analyst) → Markdown final (sections fixes) → écrit dans `output_file`

Variables d'entrée attendues :
- `{lang}`, `{header_md}`
- `{tech_table_md}`, `{summary_table_md}`, `{tech_tables_md}`
- `{ready_signals_md}`, `{triggers_md}`
- `{context_json}`, `{report_output_path}`

Règles de robustesse :
- Si `narrative_scan` ne retourne pas de sources → section « Narratifs en tendance »
  vide ou minimale, **sans invention**.
- Si la recherche est indisponible → les tâches de news affichent « Aucune source vérifiée ».

## Observabilité & coûts

**Obligatoire**
- `run_id` unique par exécution.
- Logger : `run_id`, `task_name`, `agent_name`, `duration_ms`, `token_usage` si dispo.
- Conserver les outputs intermédiaires (JSON) pour debug.

**Conseillé** — structure d'un run :
```
runs/YYYY-MM-DD/run_<run_id>/
  inputs.json
  scan_market.json
  narrative_scan.json
  tech_review.json
  report.md
  logs.txt
```

**Stratégie coût**
- Modèle « cher » réservé au reporting final ou aux narratifs difficiles.
- Cache des résultats de recherche (TTL 6–24 h) pour éviter de repayer.
