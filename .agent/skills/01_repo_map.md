# Carte du repo (où mettre quoi)

Règles
- Orchestration CrewAI : uniquement dans crew.py (+ éventuels helpers "crew/*")
- Calculs techniques : dans ta/ (purs, déterministes, testables)
- Gestion du risque : dans risk/ (purs, déterministes, testables)
- Accès externes/API : dans tools/ (I/O, retries, rate limits, cache)
- Rendu/format final : dans reporting/ (markdown final + templates)

Ce qu’on évite
- Mélanger I/O (API) et logique (TA/Risk) dans les mêmes fonctions.
- Mettre des règles “métier” dans les prompts (elles doivent vivre en code).