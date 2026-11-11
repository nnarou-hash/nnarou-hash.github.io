# Modèle de données et définitions des KPI

## Modèle logique
- **DIM_COMMERCIAUX** : un enregistrement par commercial, avec région et responsable.
- **DIM_PRODUITS** : une ligne par famille de produits.
- **OBJECTIFS_MENSUELS** : un enregistrement par mois et commercial.
- **OPPORTUNITES** : un enregistrement par opportunité, avec statut, montants, source, famille produit et dates.
- **ACTIVITES** : une ligne par interaction reliée à un commercial et à une opportunité.
- **PERFORMANCE_MENSUELLE_AGREGEE** : table de synthèse au grain mois × commercial.

Relations principales :
- `DIM_COMMERCIAUX.id_commercial` → objectifs, opportunités, activités et performance.
- `OPPORTUNITES.id_opportunite` → activités.
- `DIM_PRODUITS.famille_produit` → opportunités.
- Objectifs et performance se rapprochent par mois et commercial.

## Définitions des indicateurs
| KPI | Formule | Limite |
|---|---|---|
| CA gagné | Somme du montant gagné sur les opportunités « Gagnée » | Pas un CA facturé ni encaissé |
| Atteinte des objectifs | CA gagné / objectif × 100 | Comparer des périmètres identiques |
| Taux de transformation | Gagnées / (Gagnées + Perdues) × 100 | Exclut les opportunités en cours |
| Pipeline ouvert | Somme des montants estimés des opportunités « En cours » | Non pondéré par une probabilité |
| Panier moyen gagné | CA gagné / opportunités gagnées | Pas le panier de commande facturé |
| Cycle de vente | Moyenne des jours entre création et clôture | Dates synthétiques |
| Activité | Nombre de lignes dans ACTIVITES | Une ligne = une interaction |
| RDV & démos | Nombre de rendez-vous et démonstrations | Volume, pas qualité ni efficacité |

## Règles de grain
- Objectifs et table mensuelle : mois × commercial.
- Opportunités : une ligne par opportunité ; transformation calculée sur les opportunités closes.
- Activités : une ligne par interaction. Ne pas sommer les montants d'opportunités après une jointure directe activités-opportunités, car cela dupliquerait les montants.
- Identifiants COM, OPP, ACT et CPT fictifs.

## Lecture managériale responsable
Un classement ne doit pas être interprété seul. Le contextualiser avec le potentiel du territoire, le portefeuille, l'ancienneté, la saisonnalité, les absences, la maturité des opportunités et la qualité des données CRM. Le volume d'appels ou de rendez-vous ne prouve pas à lui seul l'efficacité commerciale.

## Limites
- Aucun client, prix, produit ou résultat réel.
- Pas de rapprochement avec une facturation ERP.
- Marge, remises, annulations, retours et impayés non modélisés.
- Pipeline non pondéré ; objectifs fictifs.
- Les données illustrent le modèle et ne définissent aucune norme de productivité.
- Avant usage réel : valider les règles de gestion avec les équipes commerciales, Finance et Data/BI, et anonymiser les données personnelles.
