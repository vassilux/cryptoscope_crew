# Structure `runs/` — Run Journal

Chaque exécution de la crew crée un dossier horodaté dans `runs/` :

```
runs/
  20260304_143022/
    scan_market.txt            # sortie brute de la task scan_market
    narrative_scan.json        # sortie validée (Pydantic) de narrative_scan
    narrative_scan.invalid.txt # (si validation échouée) sortie brute + raison
    tech_review.txt            # sortie brute de la task tech_review
    report.md                  # copie du report final
```

## Format du `run_id`

`YYYYMMDD_HHMMSS` dans la timezone configurée (`TZ` env var, défaut `Europe/Paris`).

## Comment débugger

1. **Trouver le dernier run** : le dossier le plus récent dans `runs/`.
2. **Vérifier les outputs intermédiaires** :
   - `scan_market.txt` — catalyseurs marché détectés par le researcher.
   - `narrative_scan.json` — narratifs validés via Pydantic.
     Si la validation a échoué, `narrative_scan.invalid.txt` contient la sortie
     brute et la raison de l'échec en commentaire en haut du fichier.
   - `tech_review.txt` — analyse technique détaillée par le technician.
3. **Lire le report final** : `report.md` dans le dossier du run.

## Validation Pydantic (narrative_scan)

Le schéma `NarrativeScanOutput` (dans `src/cryptoscope_crew/domain/schemas.py`)
valide automatiquement :

| Champ     | Type         | Contrainte               |
|-----------|--------------|--------------------------|
| `title`   | `str`        | obligatoire              |
| `summary` | `str`        | obligatoire              |
| `tickers` | `List[str]`  | liste (peut être vide)   |
| `heat`    | `int`        | entre 1 et 5 inclus      |
| `sources` | `List[str]`  | strings non vides filtrées |

Si le LLM retourne du texte autour du JSON, l'extracteur tente de récupérer
le premier objet `{ … }` avant validation.

**Fallback** : en cas d'échec, `{"narratives": []}` est utilisé pour ne pas
bloquer le `reporting_task`.

## Nettoyage

Les dossiers `runs/` ne sont pas supprimés automatiquement.
Pour nettoyer les anciens runs :

```bash
# Garder les 10 derniers
ls -d runs/*/ | head -n -10 | xargs rm -rf
```
