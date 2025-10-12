# Cryptoscope Crew — Analyse crypto éducative (CrewAI)

> Projet **éducatif et de recherche** sur l’analyse de marché crypto.  
> **Aucune recommandation financière. Utilisation à vos risques.**

---

## 👀 Objectif

Ce repo illustre comment :
- agréger des **données techniques** (EMA20/EMA50, RSI14) sur plusieurs paires,
- orchestrer une **pipeline d’analyse** (recherche → analyse technique → rédaction) avec **CrewAI**,
- produire un **rapport quotidien** en Markdown.

Le tout est pensé pour l’**apprentissage**, l’expérimentation et la **reproductibilité**.

---

## ⚠️ Avertissement (très important)

- Ce projet n’est **pas** un conseil en investissement.  
- Les marchés crypto sont volatils : **faites vos propres recherches** (DYOR) et n’investissez jamais plus que ce que vous pouvez perdre.  
- Le code, prompts et réglages LLM sont fournis **tels quels**, **sans garantie**. Vous êtes seul responsable de leur usage.

---

## 🧱 Stack & fonctionnalités

- **Python** (3.11+ conseillé)
- **CrewAI** pour l’orchestration des agents & tâches
- **OpenAI LLMs** (configurable par agent)
- **ccxt** pour la donnée de marché (OHLCV)
- **pandas / numpy** pour le calcul TA
- **tzdata** (Windows) pour les fuseaux horaires
- **Serper** (optionnel) pour la recherche web sourcée

---

## 📁 Structure (principaux fichiers)

```
src/cryptoscope_crew/
├─ crew.py                     # définition de la Crew, agents & tasks (+ injection des inputs)
├─ agents.yaml                 # rôles & instructions des agents
├─ tasks.yaml                  # descriptions & outputs attendus
├─ reporting/
│   ├─ __init__.py
│   └─ precompute.py           # calcul du contexte TA + table technique
├─ market/
│   ├─ __init__.py
│   └─ exchange.py             # fetch OHLCV via ccxt
├─ ta/
│   ├─ __init__.py
│   └─ ema_rsi.py              # EMA20/EMA50 + RSI14 + heuristiques simples
├─ risk/
│   ├─ __init__.py
│   └─ risk.py                 # (optionnel) helpers de sizing/risque
└─ config.py                   # lecture centralisée du .env
```

Le rapport est écrit dans `reports/` en suivant le pattern :  
`report_DDMMYYYY_HHMM.md` (ex. `report_12102025_1134.md`).

---

## 🔧 Installation

```bash
# 1) Crée un venv
python -m venv .venv
# 2) Active-le
# Windows PowerShell:
. .venv/Scripts/Activate.ps1
# macOS / Linux:
source .venv/bin/activate

# 3) Installe les deps
pip install -U pip
pip install crewai ccxt pandas numpy python-dotenv tzdata
# + optionnel : crewai-tools (Serper)
pip install crewai-tools
```

> Sur **Windows**, `tzdata` est recommandé pour `ZoneInfo("Europe/Paris")`.

---

## 🔐 Configuration (.env)

Crée un fichier `.env` à la racine du projet :

```env
# Langue & fuseau
LANG=fr
TZ=Europe/Paris

# Marché (séparés par virgules ou espaces)
PAIRS=BTC/USDC, ETH/USDC, XRP/USDC, ADA/USDC
TIMEFRAME=1d
LOOKBACK=450

# Dossier de sortie
OUTPUT_DIR=reports

# OpenAI
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
# Un modèle par agent (ou un seul modèle global OPENAI_MODEL_NAME)
OPENAI_MODEL_RESEARCHER=gpt-5
OPENAI_MODEL_TECHNICIAN=gpt-4o-mini
OPENAI_MODEL_ANALYST=gpt-4o-mini

# Optionnel: recherche web (Serper)
SERPER_API_KEY=xxxxxxxxxxxxxxxx
```

**Notes :**
- Les variables `.env` peuvent être **surclassées** par la ligne de commande (via `--inputs`).
- Si vous utilisez un modèle qui **n’accepte pas `temperature`**, le code n’enverra pas ce paramètre (patch prévu).

---

## ▶️ Exécution

### Option 1 — Par défaut (prend la config du `.env`)
```bash
crewai run
```

### Option 2 — Override rapide (sans toucher au `.env`)
```bash
crewai run --inputs timeframe=1h --inputs lookback=1200            --inputs pairs='["BTC/USDC","ETH/USDC","XRP/USDC"]'
```

Le run produit un fichier du type :
```
reports/report_12102025_1134.md
```

---

## 🧠 Comment ça marche (en bref)

1. `@before_kickoff` (dans `crew.py`) lit **LANG/TZ/PAIRS/TIMEFRAME/LOOKBACK** depuis `.env` (ou inputs CLI), fixe la date/heure et prépare le **nom de fichier** de sortie.
2. `reporting/precompute.py` calcule un **contexte TA** (EMA/RSI) + la **table technique Markdown**.
3. CrewAI exécute les **3 tâches** séquentielles :
   - `scan_market` (Chercheur) — points clés / catalyseurs (optionnellement sourcés via Serper),
   - `tech_review` (Technicien) — observations techniques à partir de la table calculée,
   - `reporting_task` (Analyste) — un **rapport synthétique** en français.

---

## 🛠️ Personnalisation

- **Langue** : `LANG=fr` par défaut → peut être forcé en tâche & agent (instructions “Réponds uniquement en {lang}.”).
- **Modèles** : un modèle par agent via `.env`  
  (`OPENAI_MODEL_RESEARCHER`, `OPENAI_MODEL_TECHNICIAN`, `OPENAI_MODEL_ANALYST`) ou `OPENAI_MODEL_NAME` global.
- **Paires** : définies dans `.env` → normalisées (`BTCUSDC` est accepté, converti en `BTC/USDC`).
- **Timeframe/Lookback** : `.env` ou `--inputs`.
- **Recherche web** : activer `SERPER_API_KEY` et le tool est attaché automatiquement au *researcher*.

---

## 🧩 Bonnes pratiques / pièges évités

- **Placeholders** : utilisez `{var}` **sans espaces** (ex: `{lang}`, **pas** `{ lang }`).  
- **Sortie FR** : la langue est verrouillée **dans les agents et les tasks** pour éviter l’anglais.  
- **Table technique** : **calculée côté code** → insérée **verbatim** (réduit les hallucinations).  
- **Température** : certains modèles (p. ex. `gpt-5`) n’acceptent **pas** de température custom → le code s’adapte.  
- **USDT vs USDC** : gardez une cohérence de cotation dans **tout** le pipeline.

---

## 🔎 Dépannage

- **`LLM Call Failed: Unsupported value: 'temperature'…`**  
  ⇒ Le modèle ne supporte pas `temperature`. Le builder LLM ne la passera pas (patch inclus).  
- **`'str' object has no attribute 'is_llm'`** en important `@llm`  
  ⇒ Nous **n’utilisons pas** le décorateur `@llm` ; l’LLM est passé **en code** dans chaque agent.  
- **Placeholders non interpolés** (`{tech_table_md}` affiché brut)  
  ⇒ Vérifiez qu’il n’y a **pas d’espace** dans `{var}` et que les clés sont bien injectées en `@before_kickoff`.  
- **Timezone (Windows)** : installez `tzdata` (`pip install tzdata`).

---

## 🛡️ Sécurité

- **NE JAMAIS** committer votre `.env`.  
- Les clés API (OpenAI/Serper/Binance, etc.) donnent accès à des services/fonds : protégez-les.

---

## 📜 Licence

- Code/discussions fournis **à titre éducatif** et **sans garantie** (“as is”).  
- Vous pouvez utiliser, modifier et forker librement à des fins d’apprentissage et de recherche.  
- Toute utilisation en production se fait **à vos risques**.

---

## 🙌 Contributions

Les issues/PR d’amélioration pédagogique (meilleurs prompts, nouveaux indicateurs, validation tests) sont bienvenues.  
Gardez l’esprit : **clarté**, **traçabilité**, **sécurité**.

Bon apprentissage & bons marchés 🚀
