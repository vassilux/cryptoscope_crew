# cryptoscope_crew

[![CI](https://github.com/vassilux/cryptoscope_crew/actions/workflows/ci.yml/badge.svg)](https://github.com/vassilux/cryptoscope_crew/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![CrewAI](https://img.shields.io/badge/Agentic-CrewAI-5a67d8)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Projet éducatif & de recherche** sur l’analyse du marché crypto, basé sur un *crew* d’agents (CrewAI) qui combinent **analyse technique multi‑timeframes**, **narratifs “hype”** (recherche web) et **rapport quotidien** en Markdown.  
> ⚠️ _Aucune recommandation d’investissement. Utilisation à vos risques._

---

## ✨ Fonctionnalités

- **Multi‑timeframes** (par défaut: `1d, 4h, 1h`) avec table TA par TF : `Close, EMA20, EMA50, RSI14, ATR14`.
- **Synthèse d’alignement** (Bull/Bear/Neutral par TF) + **“Signaux prêts à tirer”** (distances EMA/RSI avec heuristique _À portée_ via ATR).
- **Narratifs en tendance (24–72h)**: scan des thèmes (ETF, L2, RWA, AI‑coins, memecoins, airdrops…) avec **sources vérifiées** (Serper).
- **Rapport Markdown** horodaté (TZ configurable) avec sections normalisées :
  - `Points clés` • `Configuration technique` • `Synthèse multi‑timeframe`
  - `Signaux prêts à tirer` • `Triggers par paire`
  - `Narratifs en tendance` • `Risques` • `Watchlist`
- **Entièrement en français** (ou selon `{lang}`), reproductible, et **orienté spot / renforcement sur force**.

---

## 🧱 Architecture (vue rapide)

```
cryptoscope_crew/
├─ src/cryptoscope_crew/
│  ├─ crew.py                 # Définition du Crew, agents & tasks, injection des inputs
│  ├─ market/                 # Routines marché (OHLCV, indicateurs)
│  ├─ reporting/
│  │  ├─ precompute.py        # Pré‑calcul TA, tables, triggers, “signaux prêts à tirer”
│  │  └─ …
│  └─ …
├─ agents.yaml                # Rôles des agents (researcher, technician, reporting_analyst)
├─ tasks.yaml                 # Tâches (scan_market, narrative_scan, tech_review, reporting_task)
├─ reports/                   # Rapports générés (ignoré par git)
└─ ...
```

---

## 🔧 Prérequis

- Python **3.12**
- Clés API si vous activez les LLM/outils :
  - `OPENAI_API_KEY` (modèles `gpt-5`, `gpt-4o-mini`, etc.)
  - `SERPER_API_KEY` (recherche d’actus pour narratifs)
- (Optionnel) `uv` pour la gestion d’environnement rapide

---

## ⚙️ Configuration

Créez un fichier `.env` à la racine (ne pas committer vos vraies clés) :
```ini
# Langue & fuseau
LANG=fr
TZ=Europe/Paris

# Marché
PAIRS=BTC/USDC, ETH/USDC, XRP/USDC, ADA/USDC, LTC/USDC
TIMEFRAMES=1d,4h,1h
TIMEFRAME=1d
LOOKBACK=450

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL_RESEARCHER=gpt-5
OPENAI_MODEL_TECHNICIAN=gpt-4o-mini
OPENAI_MODEL_ANALYST=gpt-4o-mini

# Recherche (narratifs)
SERPER_API_KEY=serper-...

# Sortie
REPORT_DIR=reports
```

> Un fichier `.env.sample` peut être fourni à titre d’exemple (sans vraies clés).

---

## 🚀 Démarrage rapide

### Via CrewAI (recommandé)
```bash
crewai run
```

### Via Python
```bash
uv run python -m cryptoscope_crew.main
# ou
python -m cryptoscope_crew.main
```

### Paramètres utiles
Vous pouvez surcharger à l’exécution via `--inputs` :
```bash
python -m cryptoscope_crew.main   --inputs lang=fr tz=Europe/Paris timeframe=1d            pairs="BTC/USDC,ETH/USDC,XRP/USDC" lookback=450
```

- Les rapports sont générés dans `reports/` sous la forme `report_DDMMYYYY_HHMM.md`.
- Le writer force le format en sections pour une lecture immédiate.

---

## 🧠 Comment ça marche (agents & tasks)

- **researcher** : capte **catalyseurs** & **narratifs** (avec Serper).
- **technician** : commente la **table TA** (EMA/RSI/ATR) + divergences multi‑TF & invalidations.
- **reporting_analyst** : assemble le **rapport** final (sections normalisées).

**Ordre d’exécution** (séquentiel) :
1. `scan_market` → 3–5 catalyseurs du jour (+sources si dispo)
2. `narrative_scan` → 3–5 narratifs en tendance (JSON strict, sources vérifiées)
3. `tech_review` → remarques techniques & invalidations
4. `reporting_task` → rapport final Markdown

---

## 📄 Exemple de sortie (extrait)

```md
---
**Timeframes :** 1d, 4h, 1h — **Paires :** BTC/USDC, ETH/USDC, XRP/USDC, ADA/USDC
**Date :** 2025-10-14  **Heure :** 08:00  **ISO :** 2025-10-14T08:00:00+02:00 (TZ: Europe/Paris)
---

## Points clés
- ETH proche d’un reclaim daily (RSI→50) — renforcer sur force.
- BTC quasi au-dessus d’EMA50(4h) — surveiller momentum 4h.
- XRP/ADA encore loin des EMA(1d) — privilégier des entrées confirmées.

## Signaux prêts à tirer
- **ETH** — Prix=4 240 | EMA20: 0.45% à franchir | EMA50: déjà > …  | RSI=49.6 (→50: 0.4 pt)
- **BTC** — Prix=115 700 | EMA20: 1.1% à franchir | EMA50: déjà > … | RSI=48.9 (→50: 1.1 pt)
```

---

## 💸 Coûts & bonnes pratiques

- **Limiter la verbosité** (`verbose=False`) pour réduire les tokens.
- Utiliser un modèle plus économique pour les tâches narratives/techniques si nécessaire.
- Les tables/indicateurs sont calculés localement ; seules les tâches “texte” appellent l’LLM/outils.

---

## 🛡️ Avertissements

- **Éducatif uniquement** — ce projet n’est **pas** un conseil financier.
- Faites vos propres recherches (**DYOR**) et n’engagez que ce que vous pouvez vous permettre de perdre.
- Les données & sources peuvent être incomplètes ou erronées.

---

## 🗺️ Roadmap courte

- [ ] Backtests rapides sur règles “reclaim + RSI”
- [ ] Export HTML/PDF du rapport
- [ ] Tableau de bord léger (Streamlit) avec graphes EMA/RSI/ATR
- [ ] Cache des requêtes de recherche (Serper) pour réduire les coûts

---

## 🤝 Contribuer

PRs bienvenues ! Merci de :
1. Créer une branche dédiée (`feat/...`, `fix/...`).
2. Lancer la CI locale (`ruff` / dry‑run).
3. Ouvrir une PR descriptive.

---

## 📜 Licence

Ce projet est publié sous licence **MIT**. Voir le fichier `LICENSE`.
