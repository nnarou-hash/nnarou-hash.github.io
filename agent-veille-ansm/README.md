# Agent Veille Pénuries ANSM

Projet portfolio de veille documentaire sur les tensions et ruptures d'approvisionnement publiées par l'ANSM. Le socle combine collecte Python, contrôles de qualité, historisation, journal d'événements, restitution HTML et synthèse optionnelle par IA générative.

## Dashboard

Dashboard HTML : https://nnarou-hash.github.io/agent-veille-ansm/

Code source et documentation : https://github.com/nnarou-hash/nnarou-hash.github.io/tree/main/agent-veille-ansm

## Objectif

Surveiller la page publique « Disponibilité des médicaments » de l'ANSM, comparer les relevés successifs et rendre les évolutions traçables. La source porte sur les médicaments d'intérêt thérapeutique majeur (MITM) suivis par l'ANSM, notamment ceux faisant l'objet de difficultés d'approvisionnement et certaines situations récemment normalisées.

## Architecture

\`\`\`
Page publique ANSM
    -> requests + BeautifulSoup
    -> normalisation des libellés et des dates
    -> contrôle de structure (en-têtes attendus, tableau non vide)
    -> snapshot JSON horodaté + index d'historique
    -> comparaison au relevé précédent
    -> events.csv + current_signals.csv + report.json / report.md
    -> dashboard HTML /agent-veille-ansm/
    -> résumé IA optionnel (OpenAI Responses API)
\`\`\`

## Champs collectés

- Statut publié par l'ANSM
- Date de mise à jour
- Spécialité (libellé publié)
- Date de remise à disposition lorsqu'elle est renseignée
- Domaine(s) médical(aux)
- Lien vers la fiche publique lorsque disponible

La clé technique utilise le lien de détail de la spécialité lorsqu'il existe, avec un repli sur le libellé et le domaine médical.

## Fichiers générés

| Fichier | Rôle |
|---|---|
| \`data/latest_snapshot.json\` | Dernier état validé |
| \`data/history_index.json\` | Première observation, dernière observation, dernière modification et présence dans la dernière liste |
| \`data/snapshots/*.json\` | Instantanés immuables horodatés |
| \`data/current_signals.csv\` | Export CSV des entrées du dernier relevé |
| \`data/events.csv\` | Journal append-only des nouvelles entrées, modifications et sorties de liste |
| \`data/report.json\` | Agrégats par statut et domaine + changements de la collecte |
| \`data/report.md\` | Rapport textuel de la dernière collecte |
| \`data/ai_summary.md\` | Synthèse optionnelle générée par IA |

Une sortie de liste est enregistrée séparément. Elle n'est jamais assimilée automatiquement à une remise à disposition.

## Installation et exécution locale

Depuis la racine du dépôt :

\`\`\`bash
python -m venv .venv
source .venv/bin/activate  # sous Windows : .venv\\Scripts\\activate
python -m pip install -r agent-veille-ansm/requirements.txt
python -m unittest discover -s agent-veille-ansm/tests -v
python agent-veille-ansm/src/ansm_watch.py --data-dir agent-veille-ansm/data
\`\`\`

Pour refaire une collecte sur une autre copie de la page (tests ou diagnostic) :

\`\`\`bash
python agent-veille-ansm/src/ansm_watch.py --url https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments --data-dir agent-veille-ansm/data
\`\`\`

## IA générative (optionnelle)

La synthèse est produite à partir du dernier relevé validé et des derniers changements détectés. Elle ne doit pas inventer de causes, de durée de pénurie, de stocks, de dates de retour ou de recommandations thérapeutiques.

Pour l'activer localement :

\`\`\`bash
python -m pip install -r agent-veille-ansm/requirements-ai.txt
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-6-luna"  # optionnel, modèle configurable
python agent-veille-ansm/src/generate_ai_summary.py --data-dir agent-veille-ansm/data
\`\`\`

Dans GitHub, ajouter \`OPENAI_API_KEY\` dans Settings → Secrets and variables → Actions → New repository secret. Le modèle est configurable via la variable Actions \`OPENAI_MODEL\`. Sans secret, la collecte fonctionne quand même et la synthèse IA est simplement ignorée. Ne jamais mettre la clé API dans un fichier du dépôt.

L'appel IA utilise l'API Responses d'OpenAI. La génération est facultative et son coût dépend du modèle, du volume envoyé et de la fréquence de collecte.

## Automatisation et publication

Le workflow \`.github/workflows/ansm-watch.yml\` :
- vérifie la page ANSM toutes les 30 minutes (horaires UTC) ;
- peut être lancé manuellement depuis l'onglet Actions ;
- exécute les tests avant toute collecte ;
- compare les données au dernier relevé validé ;
- archive un snapshot, journalise les événements et met à jour les exports uniquement si une nouvelle entrée, une modification ou une sortie de liste est détectée ;
- ne crée aucun commit ni déploiement lorsque les données sont inchangées ;
- génère un résumé IA uniquement lorsqu'un changement est détecté et que le secret API est configuré.

La source ANSM ne déclenchant pas directement le workflow, il s'agit d'une actualisation par vérification périodique : une nouvelle publication est récupérée lors du prochain passage, puis publiée après la fin du workflow et du déploiement GitHub Pages. Un léger délai reste donc possible.

Le dashboard statique est servi depuis le dossier \`agent-veille-ansm/\` du site GitHub Pages. Il lit les fichiers générés dans \`agent-veille-ansm/data/\`. Le premier affichage reste en état « en attente » jusqu'à la première collecte réussie.

## Sources et périmètre

- ANSM — [Disponibilité des médicaments](https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments) : source opérationnelle du MVP.
- [Base de données publique des médicaments](https://base-donnees-publique.medicaments.gouv.fr/) : enrichissement futur pour rapprocher les libellés et identifiants de spécialités.
- [data.ansm](https://data.ansm.sante.fr/) : piste d'analyse historique des déclarations de ruptures et risques de rupture ; modalité d'extraction à valider avant automatisation.
- [Ministère de la Santé — Médicaments essentiels](https://sante.gouv.fr/soins-et-maladies/medicaments/article/lutte-contre-les-penuries-de-medicaments) : référentiel métier à étudier pour une éventuelle priorisation.

## Limites méthodologiques et d'usage

- La liste est centrée sur les MITM suivis par l'ANSM ; elle ne représente pas l'ensemble des médicaments commercialisés.
- Les informations de la page sont publiées par l'ANSM à partir notamment des déclarations des laboratoires. Le collecteur n'accède pas aux données privées de fabricants, grossistes-répartiteurs ou pharmacies.
- Le système ne mesure pas les stocks réels et ne prédit ni la durée d'une tension ni une date de retour.
- Une modification ou une sortie de liste est un changement de publication observé ; il faut consulter la fiche officielle pour comprendre la situation.
- Le projet est un outil de veille documentaire et de qualité des données. Il ne fournit aucun conseil médical, aucune recommandation de substitution et aucune conclusion clinique.
- Le collecteur échoue volontairement si le tableau ou les colonnes attendues ne sont plus trouvés, afin de ne pas écraser le dernier relevé valide avec des données incomplètes.

## Pistes d'évolution

- Rapprochement contrôlé avec la BDPM (identifiants, présentations et dénominations).
- Intégration historique de data.ansm après validation du format et des droits d'accès.
- Analyse de durée des états uniquement après constitution d'un historique suffisamment long.
- Ajout de règles de priorisation documentées et explicables, sans conclusion clinique.
