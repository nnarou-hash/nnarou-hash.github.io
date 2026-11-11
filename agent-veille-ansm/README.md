# Agent Veille Pénuries ANSM

Prototype de veille fondé sur les informations publiques publiées par l'ANSM.

## Objectif

Collecter la liste publique des médicaments suivis par l'ANSM, conserver un état courant, tracer les changements observés et préparer une restitution exploitable. Le projet est conçu comme un outil de veille documentaire et de qualité des données.

## Périmètre du MVP

1. Récupération de la page officielle ANSM « Disponibilité des médicaments ».
2. Extraction des champs publiés : statut, date de mise à jour, spécialité, date de remise à disposition et domaine(s) médical(aux).
3. Normalisation des dates et création d'une clé technique stable par entrée.
4. Conservation d'un instantané JSON et d'un export CSV.
5. Détection des nouvelles entrées et des modifications depuis la dernière collecte.
6. Journalisation des changements dans un fichier CSV.
7. Exécution quotidienne automatisée par GitHub Actions.

## Sources

| Source | Usage | Périmètre |
|---|---|---|
| ANSM – Disponibilité des médicaments | Source principale du MVP | Statuts publics et informations publiées par spécialité |
| Base de données publique des médicaments (BDPM) | Référentiel complémentaire envisagé | Identification et rapprochement des médicaments |
| data.ansm | Source complémentaire à étudier | Consultation d'historiques de déclarations, dont les ruptures et risques de rupture (base Trustmed), avec des données présentées depuis 2014. Le mode d'export ou l'existence d'une API exploitable restent à valider avant automatisation |
| Ministère de la Santé – Liste des médicaments essentiels | Enrichissement métier à étudier | Priorisation des molécules essentielles |

Liens :
- https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments
- https://base-donnees-publique.medicaments.gouv.fr/
- https://data.ansm.sante.fr/ (historique des déclarations ; modalités d'extraction à confirmer)
- https://sante.gouv.fr/soins-et-maladies/medicaments/article/lutte-contre-les-penuries-de-medicaments

## Intégration des sources : ordre de priorité

- **Étape 1 – Liste ANSM** : source opérationnelle du MVP, collectée à chaque exécution.
- **Étape 2 – BDPM** : référentiel d'identification pour rapprocher une spécialité de ses présentations et, lorsque c'est possible, de ses identifiants officiels. La BDPM est mise à jour mensuellement ; les fichiers et leur date de mise à jour sont publiés sur son site.
- **Étape 3 – data.ansm** : source de contexte historique pour explorer les déclarations de ruptures et de risques de rupture. La plateforme présente des données issues de la base Trustmed depuis 2014, mais son mode d'extraction devra être vérifié avant d'en faire une dépendance automatisée.
- **Étape 4 – Médicaments essentiels** : référentiel de priorisation à rapprocher des signaux, sans assimiler le caractère essentiel à une rupture effective.

## Limites à afficher clairement

- La page ANSM ne représente pas une vision exhaustive des stocks disponibles dans les laboratoires, chez les grossistes-répartiteurs ou en pharmacie.
- Le prototype ne reçoit pas les déclarations privées des industriels et n'accède pas aux systèmes Trustmed, DP-Ruptures ou TRACStocks.
- Une tension ou une rupture publiée ne permet pas, à elle seule, de quantifier les stocks ni de prédire une date de retour.
- Les données et changements détectés doivent toujours être vérifiés sur la publication officielle.
- Le projet ne fournit aucun conseil médical, aucune recommandation de substitution thérapeutique et aucune conclusion clinique.

## Installation

Depuis la racine du dépôt :

    python -m pip install -r agent-veille-ansm/requirements.txt

## Lancer une collecte

    python agent-veille-ansm/src/ansm_watch.py --data-dir agent-veille-ansm/data

La collecte crée ou met à jour :
- latest_snapshot.json : état normalisé des entrées publiées ;
- current_signals.csv : export tabulaire de l'état courant ;
- events.csv : journal append-only des nouvelles entrées et modifications détectées.

Les fichiers de données sont produits lors de la première exécution. Ils ne sont pas préremplis avec des données artificielles.

## Tests

    python -m unittest discover -s agent-veille-ansm/tests -v

## Automatisation

Le workflow GitHub Actions lance les tests et la collecte tous les jours à 06:00 UTC, et peut également être déclenché manuellement. Il ne crée un commit de données que si un fichier de suivi a changé.

## Pistes d'évolution

- Ajouter une source documentaire pour les actualités et avis ANSM.
- Rapprocher les spécialités avec les identifiants de la BDPM.
- Ajouter une couche d'analyse des durées et transitions de statut, lorsque l'historique collecté sera suffisamment long.
- Générer des résumés de changements par IA, avec citations/liens directs et séparation explicite entre faits et synthèse.
- Construire un tableau de bord de veille avec filtres, historique et indicateurs de qualité des données.
