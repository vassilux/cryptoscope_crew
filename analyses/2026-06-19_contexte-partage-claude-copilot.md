# DECISION — Contexte partagé Claude ↔ Copilot (CryptoScope)

> `Claude.md` devient la source unique du contexte projet, mirrorée vers Copilot via le script de sync.
> Date : 2026-06-19
> Périmètre :
> 1. `Claude.md` (source unique)
> 2. `.github/copilot-instructions.md` (généré)
> 3. `sync-ai-skills.ps1` / `sync-ai-skills.sh`

---

## Contexte

`Claude.md` n'est lu nativement que par Claude. GitHub Copilot, lui, charge
automatiquement `.github/copilot-instructions.md`. Sans pont, les deux assistants
travaillent avec des contextes différents → risque d'incohérence (c'est exactement
le problème noté dans l'audit du projet iClient, qui maintenait deux fichiers à la
main avec une règle « CLAUDE.md prevails »).

## Décisions

| # | Décision | Statut |
|---|----------|--------|
| D1 | `Claude.md` est la **source unique** du contexte projet (règles, archi, env) | ✅ Appliqué |
| D2 | `.github/copilot-instructions.md` est **généré** depuis `Claude.md` (copie verbatim + bannière « DO NOT EDIT ») | ✅ Appliqué |
| D3 | La génération est faite par le même script `sync-ai-skills.ps1` / `.sh` (skills + contexte) | ✅ Appliqué |
| D4 | Bannière en tête de `Claude.md` rappelant de relancer la sync après édition | ✅ Appliqué |
| D5 | Approche **génération** (vs deux fichiers maintenus à la main comme iClient) → zéro divergence | ✅ Choisi |

## Avant / Après

**Avant :**
```
Claude.md                       → Claude uniquement
(pas de .github/copilot-instructions.md)  → Copilot sans contexte projet
```

**Après :**
```
Claude.md                       ← SOURCE UNIQUE (éditée à la main)
   │  pwsh ./sync-ai-skills.ps1  |  ./sync-ai-skills.sh
   ▼
.github/copilot-instructions.md ← généré (verbatim) → Copilot (auto-chargé)
.claude (Claude.md natif)                            → Claude (auto-chargé)
```

## Reste ouvert

- Hook CI optionnel : échouer le build si `.github/copilot-instructions.md` diffère
  d'un re-render de `Claude.md` (sync oubliée).
- Le fichier généré est commité (cohérent avec le choix D5 de la réorg skills).
