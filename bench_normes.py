"""10 questions de comptabilite, avec les articles attendus (verifies dans l'index). Succes = un article attendu parmi les 3 premiers resultats."""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doctrine_mcp as dm

TESTS = [
    ("Comment comptabiliser une subvention d'investissement ?", {"312-1", "1211-13"}),
    ("Fonds dédiés d'une association : comment les comptabiliser ?", {"132-1", "132-2", "132-3", "132-4", "142-9"}),
    ("Crédit-bail : comment le locataire comptabilise-t-il les redevances ?", {"212-5"}),
    ("Produits constatés d'avance : définition et évaluation", {"321-7", "323-9", "1214-48"}),
    ("Changement de méthode comptable : conditions", {"122-1", "122-2"}),
    ("Amortissement des primes de remboursement des emprunts", {"212-10"}),
    ("Comptabilisation des amortissements dérogatoires", {"214-8", "1211-14"}),
    ("Dépréciation des stocks à la clôture", {"214-22", "214-25"}),
    ("Compte courant d'associé : quel compte utiliser ?", {"1214-45", "1121-1"}),
    ("Frais d'établissement : charge ou immobilisation ?", {"212-9"}),
]

ok = 0
for i, (q, attendus) in enumerate(TESTS, 1):
    r = dm.appeler_outil("rechercher_norme", {"requete": q})
    trouves = re.findall(r"^\[\d\] (?:PCG|RECUEIL|ASSO|CONSO) art\. ([\d\-]+)", r, re.M)
    rang = next((k for k, a in enumerate(trouves, 1) if a in attendus), None)
    ok += rang is not None
    print(f"{i:2}. {'OUI' if rang else 'non'} (rang {rang or '-'}) | {q}\n      attendu {sorted(attendus)} | obtenu {trouves}")
print(f"\nReussite : {ok}/{len(TESTS)}")
