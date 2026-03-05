# Flow d’exécution attendu (run)

Pipeline logique
1) scan_market (researcher) -> JSON {"key_drivers":[...]}
2) narrative_scan (researcher) -> JSON strict {"narratives":[...]}
3) tech_review (technician) -> JSON {"tech_notes":[...]}
4) reporting_task (reporting_analyst) -> Markdown final (sections fixes) -> écrit dans output_file

Entrées attendues (variables)
- {lang}, {header_md}
- {tech_table_md}, {summary_table_md}, {tech_tables_md}
- {ready_signals_md}, {triggers_md}
- {context_json}
- {report_output_path}

Règles de robustesse
- Si narrative_scan ne retourne pas de sources : la section "Narratifs en tendance" doit être vide (ou minimale), sans invention.
- Si la recherche est indisponible : les tâches de news doivent afficher "Aucune source vérifiée".