# Contrat agents & tâches (YAML)

Agents (config/agents.yaml)
- researcher
  - Mission : catalyseurs + narratifs + sources
  - Contraintes : pas d’invention, regrouper par narratif, heat score
- technician
  - Mission : lecture TA à partir des tables fournies
  - Contraintes : ne modifie pas les tables
- reporting_analyst
  - Mission : rapport final clair/actionnable
  - Contraintes : reproduit EXACTEMENT les blocs imposés

Tâches (config/tasks.yaml)
- scan_market -> JSON {"key_drivers":[...]}
- narrative_scan -> JSON strict {"narratives":[{title,summary,tickers,heat,sources}]}
- tech_review -> JSON {"tech_notes":[...]}
- reporting_task -> Markdown final, sections imposées, sources uniquement depuis narrative_scan