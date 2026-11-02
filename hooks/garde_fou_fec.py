# -*- coding: utf-8 -*-
"""Garde-fou avant commit : refuse tout fichier qui ressemble a un FEC reel ou a un document produit pour un client.

Active par : git config core.hooksPath hooks
Controle le CONTENU (en-tete de FEC), pas seulement le nom du fichier : un FEC renomme est bloque aussi.
Limite : contournable avec « git commit --no-verify » et inactif tant que la commande ci-dessus n'a pas ete lancee.
"""
import fnmatch
import re
import subprocess
import sys

AUTORISES = ("exemples/FEC_fictif_points_en_suspens.txt", "outils_test/*")   # fichiers fictifs publies volontairement
NOMS_INTERDITS = ("points_en_suspens_*", "TDB_*", "*.sqlite", "*.fec", "*.zip", "*.7z", "*.rar", "*.gz", "*.xlsx", "*.xls")
COLONNES_FEC = ("journalcode", "journallib", "ecriturenum", "ecrituredate", "comptenum", "comptelib", "compauxnum",
                "pieceref", "piecedate", "ecriturelib", "debit", "credit", "ecriturelet", "validdate")
RE_NOM_FEC = re.compile(r"\d{9}FEC\d{8}", re.I)


def git(*args):
    return subprocess.run(["git", *args], capture_output=True).stdout


def en_tete(contenu):
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return contenu[:4096].decode(enc, errors="strict").splitlines()[0].lower() if contenu else ""
        except (UnicodeDecodeError, IndexError):
            continue
    return ""


def main():
    fichiers = [f.decode("utf-8", "replace") for f in git("diff", "--cached", "--name-only", "--diff-filter=ACM", "-z").split(b"\0") if f]
    refus = []
    for f in fichiers:
        if any(fnmatch.fnmatch(f, a) for a in AUTORISES):
            continue
        base = f.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(base, n) for n in NOMS_INTERDITS) or RE_NOM_FEC.search(base):
            refus.append((f, "nom de fichier interdit (FEC, base, export ou archive)"))
            continue
        ligne = en_tete(git("show", ":" + f)[:4096])
        if sum(c in re.sub(r"[^a-z;|\t]", "", ligne).replace("|", ";").replace("\t", ";").split(";") for c in COLONNES_FEC) >= 5:
            refus.append((f, "l'en-tete ressemble a celui d'un FEC"))
    if refus:
        print("\nCOMMIT REFUSE : donnees clients possibles.", file=sys.stderr)
        for f, raison in refus:
            print(f"  - {f} : {raison}", file=sys.stderr)
        print("Retirer ces fichiers de l'index (git restore --staged <fichier>) et ne jamais publier de FEC reel.\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
