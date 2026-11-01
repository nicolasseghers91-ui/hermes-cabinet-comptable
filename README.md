# hermes-cabinet-comptable

Outils **100 % locaux** pour un cabinet d'expertise comptable, branchés sur un assistant IA local (agent Hermes ou tout client MCP) : contrôle de FEC, tableaux de bord de gestion, mail des points en suspens et recherche dans la doctrine fiscale et comptable officielle.

> Principe : **le modèle ne calcule rien**. Les chiffres sont produits par des programmes Python déterministes ; le modèle choisit l'outil, puis résume le résultat. Aucune donnée client ne quitte le poste.

## Contenu

| Programme | Rôle |
|---|---|
| `analyse_comptable_mcp.py` | Serveur MCP « analyse comptable » : `controler_fec`, `tableau_de_bord`, `points_en_suspens`, `lister_fichiers_comptables` |
| `controle_fec.py` | Lecture et contrôles d'un FEC : équilibre à une date d'arrêt, écritures déséquilibrées, doublons, dates hors exercice, soldes de sens inhabituel, comptes d'attente, lettrage, écritures non validées, contrôles propres au type de dossier |
| `tableau_bord.py`, `tdb_types.py` | Tableaux de bord HTML (N et N-1) : `bic`, `bnc`, `sci_ir`, `sci_is`, `association`, `esms` |
| `points_suspens.py` | Mail de demande d'information au client (voir plus bas) |
| `doctrine_mcp.py` | Serveur MCP « doctrine fiscale » : `rechercher_doctrine`, `lire_document` (BOFiP), `rechercher_boss`, `rechercher_loi`, `lire_article` (codes), `rechercher_norme`, `lire_norme` (PCG, recueil ANC) |
| `legislation.py`, `boss.py`, `normes.py` | Index et recherche : codes consolidés (CGI, LPF, CIBS, Code de commerce, Code civil, CMF, Code du travail, CSS), BOSS, normes ANC |
| `build_normes.py` | Construit `normes.sqlite` à partir des PDF de l'ANC |
| `hermes/skills/` | Consignes d'usage des outils pour le modèle (`fec-comptable`, `doctrine-fiscale`) |
| `hermes/config.exemple.yaml` | Extrait de configuration Hermes à fusionner |
| `*.bat`, `planifier_mises_a_jour.ps1` | Construction et mise à jour des données, tâche planifiée Windows, tests |
| `exemples/` | FEC fictif pour essayer `points_en_suspens` (volontairement non équilibré) |
| `outils_test/` | Générateurs de FEC fictifs pour tester les contrôles et les tableaux de bord |

## Prérequis

- **Windows 10/11** (scripts `.bat` et PowerShell ; le cœur Python est portable).
- **Python 3.9 ou plus récent.** Aucune dépendance externe pour les serveurs.
- **Hermes** (ou un autre client MCP) branché sur un **modèle local** avec appel d'outils et **au moins 64 000 jetons de contexte**.
- Accès Internet **uniquement pour construire et mettre à jour les données** (BOFiP, Légifrance, BOSS, ANC).
- Environ 1,5 Go libres pour la première construction (l'archive LEGI fait environ 1,1 Go d'après `legislation.py`) ; les bases obtenues pèsent quelques centaines de Mo.
- Pour les normes comptables uniquement : `pdftotext` (poppler) afin d'exécuter `build_normes.py`.
- Configuration matérielle testée : i7-8700K, 16 Go de RAM, RTX 3060 Ti 8 Go, Gemma 4 12B (QAT Q4) via llama.cpp, contexte 65 536. Les réponses prennent alors plusieurs minutes ; un modèle plus gros appelle mieux les outils.

## Installation

1. Cloner le dépôt, par exemple dans `C:\Users\<vous>\Documents\hermes-cabinet-comptable`.
2. Lancer `mise_a_jour_tout.bat` : construit l'index BOFiP, les codes consolidés et le BOSS (long la première fois).
3. Normes comptables : lancer `telecharger_anc.bat`, puis `python build_normes.py donnees\anc normes.sqlite`.
4. Facultatif : `planifier_mises_a_jour.bat` crée une tâche Windows quotidienne (BOFiP le lundi).
5. Fusionner `hermes/config.exemple.yaml` dans le `config.yaml` de Hermes (chemins des serveurs, dossier des compétences, dossier de travail).
6. **Quitter complètement Hermes** (icône de la zone de notification, « Quitter »), puis le rouvrir.
7. Vérifier avec `tester.bat` (appelle les mêmes fonctions que le modèle), ou en ligne de commande :

```
python -c "import analyse_comptable_mcp as m; print(m.appeler_outil('points_en_suspens', {'chemin': 'exemples/FEC_fictif_points_en_suspens.txt'}))"
```

Les bases `*.sqlite`, les FEC et les fichiers produits ne sont **pas** versionnés (voir `.gitignore`).

## Utilisation

Dans Hermes, déposer le FEC dans le dossier de travail, puis par exemple :

- « Contrôle le FEC_2026.txt » (ajouter la nature du dossier pour les contrôles spécifiques).
- « Fais le tableau de bord du FEC_2026.txt, c'est une SARL » → page HTML.
- « Prépare le mail de points en suspens du FEC_2026.txt » → fichier HTML à copier dans Outlook ; le modèle n'en donne qu'un résumé.
- « Une société à l'IS peut-elle bénéficier de l'exonération du 151 septies du CGI ? » → lecture de l'article puis du BOFiP.

### Points en suspens : règles de calcul

- Factures clients (411, 413, 416) et fournisseurs (401, 404) non réglées depuis plus de 3 mois, une ligne par facture ; seuil modifiable (`mois`).
- Règlements et avoirs non lettrés imputés sur les factures les plus anciennes ; les règlements restant sans facture sont listés dans deux rubriques distinctes (clients, fournisseurs).
- Opérations à justifier : écritures non lettrées des comptes d'attente 471 à 473 (hypothèse de travail à confirmer pour chaque cabinet).
- Restes inférieurs à 10 € ignorés (`montant_min`). Report à nouveau : ancienneté inconnue, indiquée « avant le début d'exercice ».
- Le mail porte les noms comptables du FEC : à relire avant envoi, le lettrage manquant pouvant expliquer certains points.

## Sources des données (non redistribuées)

Les données sont téléchargées sur votre poste à la construction. Chaque source suit sa propre licence, à vérifier avant tout usage :

- BOFiP-Impôts en vigueur (DGFiP, data.economie.gouv.fr) : Licence Ouverte v2.0.
- Codes consolidés, base LEGI (DILA) : Licence Ouverte v2.0.
- BOSS (boss.gouv.fr) : contenus indiqués sous licence ODbL dans ses mentions légales.
- Normes comptables (anc.gouv.fr) : textes publics de l'ANC.

## Limites et précautions

- Outil d'aide à la décision : ni conseil juridique, ni conseil fiscal. Tout résultat doit être relu par un professionnel et rapproché des textes officiels.
- La recherche dans la doctrine est lexicale : elle peut manquer un document pertinent. Les skills demandent au modèle de lire l'article puis le BOFiP, mais un petit modèle peut ne pas suivre toutes les consignes.
- Les tests ont porté sur des FEC pseudonymisés ou fictifs, sur un nombre limité de configurations.
- **Confidentialité** : les serveurs lisent les FEC localement. Les tableaux de bord HTML chargent Chart.js depuis un CDN (le navigateur contacte ce site, sans y envoyer de données du FEC). Vérifier dans Hermes que les outils pouvant joindre Internet sont désactivés pour les dossiers clients, et que le modèle utilisé est bien local.
- Les FEC restent dans le dossier de travail de Hermes, hors du dépôt. Seul le fichier fictif de `exemples/` est publié. Le `.gitignore` bloque les noms de fichiers courants, mais pas un FEC renommé : vérifier avant tout `git add`.

## Licence

Code et documentation : [Creative Commons Attribution – Pas d'Utilisation Commerciale 4.0 International (CC BY-NC 4.0)](LICENSE). Les licences Creative Commons ne sont pas spécifiquement conçues pour les logiciels : en cas de réutilisation professionnelle, demander l'accord de l'auteur.
