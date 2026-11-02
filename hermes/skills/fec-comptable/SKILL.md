---
name: fec-comptable
description: Controler un FEC (ecart, desequilibre, anomalies), produire un tableau de bord de gestion ou preparer le mail de points en suspens (pieces manquantes, clients et fournisseurs impayes) a partir d'un FEC, via les outils MCP analyse_comptable.
---
# FEC : toujours passer par les outils

- Controle d'un FEC ou ecart a une date : appelle `mcp__analyse_comptable__controler_fec` avec `chemin` = nom du fichier (ex. FEC_Pseudonymise.txt). Si l'utilisateur donne une date, ajoute `date_arrete` (JJ/MM/AAAA). Si l'utilisateur dit la nature du dossier (SARL, association, SCI, liberal...), ajoute `type_dossier` (bic, bnc, sci_ir, sci_is, association, esms) pour lancer les controles propres au type ; sinon laisse-le vide et ne le demande pas. Ne demande aucun autre parametre. Reponds d'abord a la question posee (ecart, ecriture, cause), puis resume les autres constats en une phrase.
- Tableau de bord : appelle `mcp__analyse_comptable__tableau_de_bord` avec `chemin` et `type_dossier` (bic, bnc, sci_ir, sci_is, association, esms). Si le type n'est pas donne, demande-le a l'utilisateur.
- Points en suspens, pieces manquantes, clients ou fournisseurs non payes depuis plus de 3 mois, reglements sans facture, mail de demande d'information : appelle `mcp__analyse_comptable__points_en_suspens` avec `chemin` seulement (ajoute `date_arrete`, `nom_client`, `destinataire`, `signataire`, `delai` uniquement si l'utilisateur les a donnes ; ne les demande pas). L'outil ecrit le mail dans un fichier HTML : reponds en 3 ou 4 lignes (resume chiffre de l'outil, chemin du fichier a ouvrir pour le copier dans Outlook, mention "a lettrer en interne" si elle est renvoyee). Ne recopie jamais le mail. Si l'utilisateur veut un fichier Excel plutot que le mail, ajoute `format` = excel. Si l'utilisateur veut le lire dans la conversation, relance l'outil avec `afficher_mail` = oui et restitue-le tel quel, sans changer un montant ni un nom. Ne l'envoie pas.
- Fichier introuvable : appelle `mcp__analyse_comptable__lister_fichiers_comptables`.
- N'ouvre, ne liste et ne lis jamais le FEC toi-meme. Ne calcule rien : cite uniquement les chiffres renvoyes par l'outil.
