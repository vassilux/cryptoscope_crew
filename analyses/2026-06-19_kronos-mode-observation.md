# DECISION — Kronos en mode observation (CryptoScope)

> Intégration du foundation model Kronos pour la prévision de K-lines, **sans** impact sur les décisions de trading.
> Date : 2026-06-19 (entrée rétroactive — décision antérieure)
> Périmètre :
> 1. `src/cryptoscope_crew/forecast/kronos_model/` (modèle vendorisé, MIT)
> 2. `src/cryptoscope_crew/forecast/kronos.py` (wrapper)
> 3. Rapport de run + `kronos_forecast.json`
> 4. `tests/test_kronos.py`

---

## Contexte

On souhaite explorer la valeur prédictive d'un foundation model de séries temporelles
(Kronos, https://github.com/shiyu-coder/Kronos, licence MIT) sur les K-lines OHLCV,
**sans** risquer de polluer le pipeline de décision existant (TA + on-chain + sentiment).

Le modèle est vendorisé dans le repo pour éviter une dépendance externe fragile ;
les poids sont téléchargés depuis HuggingFace au premier run.

## Décisions

| # | Décision | Statut |
|---|----------|--------|
| D1 | Kronos vendorisé sous `forecast/kronos_model/` (MIT) + wrapper `forecast/kronos.py` | ✅ Appliqué |
| D2 | **Mode observation seulement** : n'entre ni dans le score de conviction ni dans les décisions | ✅ Appliqué |
| D3 | Sortie injectée comme section « Kronos Forecast » du rapport + `kronos_forecast.json` par run | ✅ Appliqué |
| D4 | Pilotable par env : `KRONOS_ENABLED` (1 défaut), `KRONOS_TIMEFRAME` (4h), `KRONOS_PRED_LEN` (24), `KRONOS_LOOKBACK` (400, max 512), `KRONOS_SAMPLE_COUNT` (1), `KRONOS_MODEL` | ✅ Appliqué |
| D5 | Exécution CPU acceptable (~10 s/paire en Kronos-small) | ✅ Validé |

## Avant / Après

**Avant :** décisions basées uniquement sur TA + on-chain + sentiment ; aucune prévision ML.

**Après :** chaque run produit en plus une prévision Kronos (observation), tracée dans le
rapport et un JSON dédié, **isolée** du chemin de décision (respecte la Hard Rule
« Sentiment = contexte, pas signal », appliquée ici aussi à la prévision ML).

## Reste ouvert

- Backtest de la qualité prédictive Kronos avant toute promotion en signal.
- Décider d'un critère explicite si Kronos devait un jour entrer dans le score de conviction
  (nécessiterait une nouvelle entrée `DECISION` actant le changement de Hard Rule).
