# Cryptoscope Crew — Contexte

Objectif
- Produire un rapport crypto quotidien/actionnable basé sur :
  - un scan news/narratifs (avec sources vérifiées si possible),
  - une analyse technique à partir de tables calculées en amont,
  - une synthèse finale structurée (sections fixes).

Principes non négociables
- Ne pas inventer de liens ni de sources.
- Les tâches qui exigent du JSON doivent retourner du JSON strict (sans texte autour).
- L’analyste technique ne modifie jamais les tables fournies.
- Le reporting reproduit exactement les blocs imposés (header/table), puis complète.

Arborescence (source)
- src/cryptoscope_crew/
  - crew.py : orchestration CrewAI
  - main.py : point d’entrée
  - config/ : agents.yaml, tasks.yaml (contrat agents/tasks)
  - market/, ta/, risk/, reporting/, tools/ : logique métier par domaine