# Schémas de sortie (contrats machine)

scan_market
- Type : JSON strict
- Schema : {"key_drivers": [string, ...]}
- Règles : 3–5 éléments, 1 phrase chacun, + (optionnel) 1 lien max par bullet si vérifié

narrative_scan
- Type : JSON strict, sans texte autour
- Schema :
{
  "narratives": [
    {
      "title": "string",
      "summary": "string",
      "tickers": ["string", ...],
      "heat": 1..5,
      "sources": ["https://...", ...]
    }
  ]
}
- Règles : sources = URLs vérifiées seulement, heat cohérent, tickers non modifiés

tech_review
- Type : JSON strict
- Schema : {"tech_notes":[string,...]}
- Règles : 3–5 observations, inclure invalidations si possible

reporting_task
- Type : Markdown final (sans ```), sections fixes et uniques
- Règles : n’afficher un narratif que si au moins 1 source existe