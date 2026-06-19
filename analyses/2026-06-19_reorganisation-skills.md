# EVOLUTION — Réorganisation des skills (source unique + sync) (CryptoScope)

> Mise en place d'une source unique de vérité `ai/skills/` synchronisée vers Copilot et Claude.
> Date : 2026-06-19
> Périmètre :
> 1. `.claude/skills/**` (état initial)
> 2. `ai/skills/**/SKILL.md` (nouvelle source)
> 3. `.github/skills/**`, `.claude/skills/**` (générés)
> 4. `sync-ai-skills.ps1` / `sync-ai-skills.sh`
> 5. `Claude.md`

---

## Contexte

Les 6 skills du projet (`crewai-agent`, `pydantic-schema`, `ccxt-tool`, `ta-tool`,
`sentiment-tool`, `kronos`) vivaient uniquement sous `.claude/skills/` à plat, donc
visibles par Claude mais **pas par GitHub Copilot** (qui lit `.github/skills/`).
Aucune source unique : risque de divergence entre les deux assistants.

On reproduit le système déjà en place sur le projet iClient (`M1ClientWeb`) :
une source catégorisée `ai/skills/` + un script de sync qui aplatit par nom de skill.

## Décisions

| # | Décision | Statut |
|---|----------|--------|
| D1 | `ai/skills/<catégorie>/<skill>/SKILL.md` devient la **source unique de vérité** | ✅ Appliqué |
| D2 | Catégories : `framework/` (crewai-agent, pydantic-schema) et `tools/` (ta-tool, ccxt-tool, sentiment-tool, kronos) | ✅ Appliqué |
| D3 | `.github/skills/` et `.claude/skills/` sont **générés** (copies réelles, pas de symlink) — ne pas éditer à la main | ✅ Appliqué |
| D4 | Scripts `sync-ai-skills.ps1` (Windows/CI) et `sync-ai-skills.sh` (Linux/macOS) à la racine | ✅ Appliqué |
| D5 | Dossiers générés **commités** (comme iClient), pas ignorés par Git | ✅ Appliqué |
| D6 | Documentation du système dans `Claude.md` | ✅ Appliqué |

## Avant / Après

**Avant :**
```
.claude/skills/<skill>/SKILL.md   (6 skills, à plat, Claude uniquement)
(pas de .github/skills/, pas de ai/)
```

**Après :**
```
ai/skills/                         ← SOURCE UNIQUE (catégorisée)
├── framework/{crewai-agent, pydantic-schema}/SKILL.md
└── tools/{ta-tool, ccxt-tool, sentiment-tool, kronos}/SKILL.md
        │  pwsh ./sync-ai-skills.ps1  |  ./sync-ai-skills.sh
        ▼
.github/skills/  ← 6 copies réelles → Copilot
.claude/skills/  ← 6 copies réelles → Claude Code
```

## Reste ouvert

- Hook CI optionnel : vérifier que `.github/skills` / `.claude/skills` sont à jour
  vs `ai/skills` (échouer le build si la sync n'a pas été relancée).
- Pas de `.github/copilot-instructions.md` repo-wide à ce jour (seul `Claude.md` existe).
