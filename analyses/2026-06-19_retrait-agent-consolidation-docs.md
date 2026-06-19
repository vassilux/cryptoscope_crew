# EVOLUTION — Retrait de `.agent/`, consolidation dans `docs/ARCHITECTURE.md` (CryptoScope)

> Les notes orphelines `.agent/skills/` sont consolidées en doc de référence vivante, lue par les deux assistants via référence depuis `Claude.md`.
> Date : 2026-06-19
> Périmètre :
> 1. `.agent/skills/**` (supprimé)
> 2. `docs/ARCHITECTURE.md` (créé)
> 3. `Claude.md` (référence + correction structure)
> 4. `.github/copilot-instructions.md` (régénéré)

---

## Contexte

`.agent/skills/` contenait d'anciennes notes numérotées (`00`–`06`) **non lues** par
Claude (`Claude.md`, `.claude/skills/`) ni par Copilot (`.github/`). Doc orpheline,
en grande partie déjà couverte par `Claude.md` et les skills `crewai-agent` /
`pydantic-schema`. La ligne `├── .agent/  # CrewAI agent definitions` de `Claude.md`
était de plus inexacte (les vrais agents sont dans `config/agents.yaml` + `src/cryptoscope_crew/`).

## Décisions

| # | Décision | Statut |
|---|----------|--------|
| D1 | Conserver les 3 éléments utiles (carte du repo, flow d'exécution, observabilité) | ✅ Appliqué |
| D2 | Les consolider en **doc de référence vivante** `docs/ARCHITECTURE.md` (pas dans `analyses/` qui reste le journal de décisions) | ✅ Appliqué |
| D3 | Référencer `docs/ARCHITECTURE.md` **uniquement depuis `Claude.md`** → propagé à Copilot via la sync (pas d'édition manuelle de `copilot-instructions.md`) | ✅ Appliqué |
| D4 | Supprimer `.agent/` (contenu unique migré, reste redondant) | ✅ Appliqué |
| D5 | Corriger la ligne inexacte `.agent/` dans la structure de `Claude.md` | ✅ Appliqué |

## Avant / Après

**Avant :**
```
.agent/skills/00..06_*.md   ← orphelin (lu par personne)
Claude.md mentionne .agent/ (description inexacte)
```

**Après :**
```
docs/ARCHITECTURE.md        ← référence vivante (repo map + flow + observabilité)
   ▲ référencé par
Claude.md  ──sync──▶  .github/copilot-instructions.md   (accessible aux 2 assistants)
(.agent/ supprimé)
```

## Reste ouvert

- Vérifier que les emplacements cités dans `docs/ARCHITECTURE.md` (`ta/`, `risk/`,
  `reporting/`, `crew.py`) reflètent l'arborescence réelle sous `src/cryptoscope_crew/`
  et réaligner si divergence.
