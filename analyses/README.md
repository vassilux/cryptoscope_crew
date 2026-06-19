# analyses/

Journal d'analyses et d'évolutions structurantes du projet CryptoScope.

> **But** : garder une mémoire long-terme du **contexte projet** et des **décisions
> d'architecture / gouvernance**. Complémentaire de `runs/` (exécutions du bot) et
> `reports/` (rapports de marché). Ici on consigne *pourquoi* le projet évolue, pas
> *ce que le bot a tradé*.

## Quand créer une entrée

- Réorganisation de structure (skills, modules, packaging)
- Décision d'architecture (nouvel agent, nouveau tool, changement de flux)
- Audit de cohérence (gouvernance IA, dépendances, sécurité)
- Migration / refonte (nouvelle lib, nouvelle source de données)

## Convention de nommage

```
analyses/AAAA-MM-JJ_sujet-court.md
```

Exemples :
- `2026-06-19_reorganisation-skills.md`
- `2026-07-02_ajout-agent-onchain.md`

## Format d'une entrée

Chaque fichier suit cette trame :

```markdown
# <TYPE> — <Titre> (CryptoScope)

> Résumé en une phrase.
> Date : AAAA-MM-JJ
> Périmètre : fichiers / dossiers concernés

## Contexte
Pourquoi cette évolution.

## Décisions
Ce qui a été décidé / appliqué (tableau de statut si pertinent).

## Avant / Après
État avant vs état après.

## Reste ouvert
Points non traités, dette, suites possibles.
```

`<TYPE>` ∈ `ASSESSMENT` (audit), `EVOLUTION` (changement appliqué), `DECISION` (ADR léger).
