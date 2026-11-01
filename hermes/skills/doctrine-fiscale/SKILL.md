---
name: doctrine-fiscale
description: Repondre a toute question de droit fiscal, comptable ou social (CGI, BOFiP, TVA, IS, IR, plus-values, PCG, BOSS, codes) en lisant les textes via les outils MCP doctrine_fiscale, jamais de memoire.
---
# Doctrine fiscale : toujours lire les textes avant de repondre

- Pour toute question sur une regle, un seuil, un article ou une doctrine : appelle d'abord les outils `mcp__doctrine_fiscale__...` AVANT d'ecrire la reponse. Ne reponds jamais de memoire : un article, un seuil ou un taux cite sans appel d'outil est a considerer comme faux.
- Article cite par l'utilisateur (ex. "151 septies du CGI") : `mcp__doctrine_fiscale__lire_article` avec `code` = CGI et `numero` = 151 septies, puis `mcp__doctrine_fiscale__rechercher_doctrine` pour le BOFiP.
- Question sans article : `mcp__doctrine_fiscale__rechercher_doctrine` (BOFiP) ou `mcp__doctrine_fiscale__rechercher_loi` (codes), avec des mots-cles francais ; puis `mcp__doctrine_fiscale__lire_document` (identifiant BOI-...) ou `lire_article` pour le texte exact.
- Paie et cotisations : `mcp__doctrine_fiscale__rechercher_boss`. Comptabilite (PCG, associations) : `mcp__doctrine_fiscale__rechercher_norme` puis `lire_norme`.
- Si l'outil n'apparait pas dans ta liste : `tool_search` (mot-cle "doctrine"), puis `tool_describe`, puis appelle-le.

## Lire en entier
- Si le resultat se termine par "[Suite : lire_article(..., page=N)]" ou "[Suite : lire_document(..., passage=N)]", appelle la suite et lis TOUTES les pages avant de repondre. Un article lu a moitie donne une reponse fausse (les exceptions, seuils partiels et limites sont souvent plus loin).
- Un extrait de `rechercher_doctrine` est un apercu : pour un point important, ouvre le document avec `lire_document`.
- Apres avoir lu l'article en entier, ouvre TOUJOURS un document BOFiP avant de repondre : le texte de loi ne dit pas tout (beneficiaires, exclusions, precisions). Le bas de l'article indique "[BOFiP citant le plus cet article : lire_document(...)]" : appelle `lire_document` sur celui dont le titre correspond a la question. Sinon utilise `rechercher_doctrine`.
- Question "qui peut en beneficier ?", "une societe / une association / un particulier peut-il ?" : ouvre le BOFiP dont le titre dit "Champ d'application" ou "Personnes visees" ; c'est lui qui donne les exclusions.

## Repondre
- Premiere phrase = reponse directe a la question posee (oui / non / depend de, avec la raison en une phrase). Les conditions et seuils viennent ensuite, seulement s'ils servent a repondre.
- Reponds uniquement avec ce que les passages lus disent. Recopie les mots du texte pour les conditions et seuils, ne les reformule pas, n'ajoute aucun mot entre parentheses qui n'est pas dans le texte.
- Cite l'article ou l'identifiant BOFiP avec le paragraphe. Distingue ce qui vient de l'article de ce qui vient du BOFiP, et ne melange pas deux articles voisins (ex. 151 septies et 151 septies A) : precise toujours de quel article vient chaque point.
- N'utilise pas un passage hors sujet comme preuve. Rien trouve : dis-le, n'invente rien.
- Reponse breve : regle, conditions, seuils, sources.
