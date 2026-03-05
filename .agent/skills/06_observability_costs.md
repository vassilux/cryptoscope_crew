# Observabilité & coûts

Obligatoire
- run_id unique par exécution
- logger : run_id, task_name, agent_name, duration_ms, token_usage si dispo
- conserver les outputs intermédiaires (JSON) pour debug

Conseillé
- dossier runs/YYYY-MM-DD/run_<run_id>/
  - inputs.json
  - scan_market.json
  - narrative_scan.json
  - tech_review.json
  - report.md
  - logs.txt

Stratégie coût
- modèle “cher” uniquement pour reporting final ou narratifs difficiles
- cache des résultats de recherche (TTL 6–24h) pour éviter de repayer