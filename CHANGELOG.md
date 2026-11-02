# Journal des modifications

## 2026-11-02
- Points en suspens : journal d'à-nouveaux reconnu aussi par son libellé (« A NOUVEAU », même avec le code 00) ; écritures de banque limitées aux comptes 511, 512, 514, 519 et 53 (les intérêts courus 518 n'en sont plus) ; nombres de lignes numériques dans le classeur Excel.
- Points en suspens : l'auxiliaire « clients divers » (ou « div. ») est reconnu aussi lorsque son code est accolé (CLIENTDIVERS, CLIESPECES…).
- Points en suspens : les à-nouveaux non lettrés ne sont plus repris (totalisés dans les notes). Côté clients, sont écartés les lignes en 411 sans auxiliaire et les comptes clients « espèces », « CB », « carte bleue », « chèques », « caisse » ou « clients divers » (compte général ou auxiliaire) ; avec un seul client, les clients ne sont pas contrôlés.
- Points en suspens : contrôle refondu sur le lettrage. Seules les lignes non lettrées sont reprises, sans imputation sur les soldes ; les règlements sans facture sont les lignes non lettrées des écritures de banque ou de caisse (51, 53) ; un lettrage postérieur à la fin du FEC compte comme lettré (sauf `date_arrete` explicite). Avoirs, OD, à-nouveaux et lettrages partiels sont signalés dans les notes internes.
- Points en suspens : les règlements de fournisseurs sans facture sont tous repris, quelle que soit leur date (les règlements de clients restent limités aux plus de 3 mois).
- Points en suspens : en plus du mail HTML, un classeur Excel des mêmes listes est toujours écrit (une feuille par rubrique, montants numériques). Un petit modèle local créait sinon son propre fichier à partir du HTML.
- Points en suspens : tiers classés par ordre alphabétique (sans tenir compte des accents ni de la casse).
- Garde-fou anti-FEC (`hooks/`) : refus de tout commit contenant un FEC, même renommé, ou un export client.

## 2026-11-01
- Première publication : serveurs MCP « analyse comptable » (contrôle de FEC, tableaux de bord, points en suspens) et « doctrine fiscale » (BOFiP, codes, BOSS, normes ANC), compétences Hermes, scripts de construction des données.
