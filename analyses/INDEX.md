# Index des analyses

> Scan rapide du journal `analyses/`. **À mettre à jour à chaque nouvelle entrée**
> (une ligne : date, type, titre, résumé). Plus récent en haut.
> Un agent consulte cet index **avant toute décision d'architecture/gouvernance**,
> puis n'ouvre que l'entrée pertinente.

| Date | Type | Entrée | Résumé |
|------|------|--------|--------|
| 2026-06-19 | EVOLUTION | [retrait `.agent/`, consolidation docs](2026-06-19_retrait-agent-consolidation-docs.md) | Suppression des notes orphelines `.agent/skills/`, consolidées en doc de référence vivante `docs/ARCHITECTURE.md`. |
| 2026-06-19 | DECISION | [contexte partagé Claude ↔ Copilot](2026-06-19_contexte-partage-claude-copilot.md) | `Claude.md` = source unique, mirrorée vers `.github/copilot-instructions.md` via la sync (zéro divergence). |
| 2026-06-19 | DECISION | [Kronos en mode observation](2026-06-19_kronos-mode-observation.md) | Kronos vendorisé ; prévision affichée dans le rapport mais **jamais** utilisée dans les décisions. |
| 2026-06-19 | EVOLUTION | [réorganisation des skills](2026-06-19_reorganisation-skills.md) | Source unique `ai/skills/` (framework/, tools/) aplatie vers `.github/skills` et `.claude/skills` par le script de sync. |
