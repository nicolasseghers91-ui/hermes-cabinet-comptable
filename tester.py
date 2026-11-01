"""Teste a la main les recherches du serveur « Doctrine fiscale », sans passer par le modele.

Ce sont exactement les fonctions que le modele appelle : ce que tu vois ici est ce qu'il recoit.
Chaque essai est aussi enregistre dans journal_tests.txt (a coller dans la conversation si besoin).
"""
import datetime
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import doctrine_mcp as dm  # noqa: E402
import analyse_comptable_mcp as ac  # noqa: E402

SOURCES = {
    "1": ("rechercher_doctrine", "BOFiP (ajoute le BOSS pour une question de paie, le Code du travail pour le droit du travail)"),
    "2": ("rechercher_boss", "BOSS (paie, cotisations, avantages en nature)"),
    "3": ("rechercher_loi", "Codes (CGI, LPF, CIBS, COM, CIV, CMF, CT, CSS) - mots-cles ou « article 279 CGI »"),
    "4": ("rechercher_norme", "Normes comptables (PCG, recueil ANC, associations, consolidation)"),
    "5": ("lire_document", "Lire un document : BOI-... ou BOSS-... (puis numero de passage)"),
    "6": ("lire_article", "Lire un article de code (code puis numero)"),
    "7": ("lire_norme", "Lire un article du PCG / recueil (ex. PCG art. 214-9)"),
    "8": ("controler_fec", "Controler un FEC (nom du fichier, date d'arret facultative)"),
    "9": ("tableau_de_bord", "Tableau de bord d'un FEC (bic, bnc, sci_ir, sci_is, association, esms) -> page HTML dans le dossier sorties"),
}
OUTILS_COMPTA = ("controler_fec", "tableau_de_bord")


def demander(texte, defaut=""):
    try:
        v = input(texte).strip()
    except EOFError:
        return None
    return v or defaut


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    journal = os.path.join(ICI, "journal_tests.txt")
    print("Test des recherches. Laisse la recherche vide pour quitter.")
    source = "1"
    while True:
        print()
        for k, (_, d) in SOURCES.items():
            print(f"  {k} = {d}")
        s = demander(f"Source [{source}] : ", source)
        if s is None:
            return
        if s not in SOURCES:
            print("Choix inconnu.")
            continue
        source = s
        outil = SOURCES[s][0]
        args = {}
        if outil in ("rechercher_doctrine", "rechercher_boss", "rechercher_loi", "rechercher_norme"):
            q = demander("Recherche : ")
            if not q:
                return
            args = {"requete": q}
        elif outil in ("lire_document", "lire_norme"):
            ident = demander("Identifiant : ")
            if not ident:
                return
            args = {"identifiant": ident, "passage": demander("Passage [1] : ", "1")}
        elif outil == "controler_fec":
            chemin = demander("Chemin du FEC : ")
            if not chemin:
                return
            args = {"chemin": chemin}
            arrete = demander("Date d'arret JJ/MM/AAAA (vide = aucune) : ")
            if arrete:
                args["date_arrete"] = arrete
            ecr = demander("Ecriture a detailler JOURNAL:NUMERO (vide = aucune) : ")
            if ecr:
                args["ecriture"] = ecr
        elif outil == "tableau_de_bord":
            chemin = demander("Nom du FEC de l'exercice N : ")
            if not chemin:
                return
            args = {"chemin": chemin}
            typ = demander("Type de dossier (bic, bnc, sci_ir, sci_is, association, esms ; vide = l'outil pose la question) : ")
            if typ:
                args["type_dossier"] = typ
            for cle, texte in (("chemin_n1", "Nom du FEC N-1 (vide = sans comparaison) : "), ("date_arrete", "Date d'arret JJ/MM/AAAA (vide = tout le fichier) : "),
                               ("nom_client", "Nom du dossier pour le titre (vide = « dossier ») : ")):
                v = demander(texte)
                if v:
                    args[cle] = v
            if typ.lower().startswith("sci"):
                for cle, texte in (("valeur_bien", "Valeur du bien en euros (facultatif) : "), ("surface_m2", "Surface en m2 (facultatif) : ")):
                    v = demander(texte)
                    if v:
                        args[cle] = v
            if typ.lower() in ("esms", "ehpad", "ime", "esat", "mas", "fam", "chrs"):
                for cle, texte in (("journees_realisees", "Journees realisees (facultatif) : "), ("journees_theoriques", "Journees theoriques (facultatif) : ")):
                    v = demander(texte)
                    if v:
                        args[cle] = v
        else:
            code = demander("Code (CGI, CT...) : ")
            if not code:
                return
            args = {"code": code, "numero": demander("Numero d'article : ")}
        try:
            reponse = (ac if outil in OUTILS_COMPTA else dm).appeler_outil(outil, args)
        except Exception as e:  # noqa: BLE001
            reponse = f"Erreur : {e}"
        print("\n" + "=" * 70 + "\n" + reponse + "\n" + "=" * 70)
        with open(journal, "a", encoding="utf-8") as f:
            f.write(f"\n##### {datetime.datetime.now():%d/%m/%Y %H:%M} | {outil} | {args}\n{reponse}\n")


if __name__ == "__main__":
    main()
