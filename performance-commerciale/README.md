# Pilotage de la performance commerciale

## Objectif
Construire un cas d’usage de Business Intelligence pour piloter une équipe commerciale : objectifs, chiffre d’affaires gagné, taux de transformation, pipeline, activité et résultats par commercial/région.

## État
**Socle de données et prototype de lecture préparés.** Le travail suivant portera sur l'analyse métier, l'interprétation des écarts et les recommandations managériales.

## Périmètre
- Janvier 2024 à décembre 2025
- 12 commerciaux fictifs et 4 régions
- 5 familles de produits fictives
- 288 couples mois-commercial
- 3178 opportunités
- 9596 activités

Toutes les données, personnes, entreprises clientes, valeurs et performances sont **entièrement synthétiques**. Elles ne décrivent ni Teva, ni Picard, ni une autre entreprise réelle.

## Fichiers
| Fichier | Grain | Utilisation |
|---|---|---|
| `data/dim_commerciaux.csv` | 1 ligne par commercial | Référentiel équipe |
| `data/dim_produits.csv` | 1 ligne par famille produit | Référentiel produits |
| `data/objectifs_mensuels.csv` | 1 ligne par mois et commercial | Objectifs |
| `data/opportunites.csv` | 1 ligne par opportunité | Pipeline, gagnées/perdues, montants, sources |
| `data/activites.csv` | 1 ligne par interaction | Appels, rendez-vous, devis, démos |
| `data/performance_mensuelle_agregee.csv` | 1 ligne par mois et commercial | Table analytique agrégée |
| `docs/modele_donnees_et_kpi.md` | Référentiel | Relations, formules et limites |

## Prototype
Ouvrir [le dashboard de cadrage](./index.html). Filtres par période, région et commercial.

## Prochaines étapes
1. Valider les KPI avec un besoin métier précis.
2. Ajouter, si possible, ventes facturées, marge et segmentation client.
3. Distinguer commandes signées, CA facturé et CA encaissé.
4. Analyser les écarts en tenant compte du portefeuille et du potentiel commercial.
5. Formuler des recommandations à destination des managers et des équipes terrain.
