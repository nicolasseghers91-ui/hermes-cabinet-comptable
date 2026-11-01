# -*- coding: utf-8 -*-
"""
Construit normes.sqlite (normes comptables ANC) a partir des PDF de l'ANC.
pdftotext (poppler) est requis. Les PDF sont telecharges par telecharger_anc.bat ; le fichier produit
(normes.sqlite) se place a cote de doctrine_mcp.py.

  python3 build_normes.py DOSSIER_PDF SORTIE.sqlite
"""
import os
import re
import sqlite3
import subprocess
import sys
import time

SOURCES = [  # (code, fichier, libelle, url publique)
    ("PCG", "pcg-2026.pdf",
     "PCG - Reglement ANC 2014-03 (version consolidee au 1er janvier 2026)",
     "https://www.anc.gouv.fr/files/anc/files/1_Normes_fran%C3%A7aises/recueil/2026/PCG--1er-janvier-2026.pdf"),
    ("RECUEIL", "recueil-entreprises-2026.pdf",
     "Recueil des normes comptables des entreprises 2026 (PCG + commentaires de doctrine CNC/ANC)",
     "https://www.anc.gouv.fr/files/anc/files/1_Normes_fran%C3%A7aises/recueil/2026/Recueil-PCG-Janvier-2026-2-.pdf"),
    ("ASSO", "recueil-non-lucratif-2026.pdf",
     "Recueil des normes comptables du secteur non lucratif 2026 (reglement ANC 2018-06, associations et fondations)",
     "https://www.anc.gouv.fr/files/anc/files/1_Normes_fran%C3%A7aises/Reglements/Recueils/Recueil_Secteur-non-lucratif/2026/Recueil-non-lucratif-2026.pdf"),
    ("CONSO", "reglement-2020-01-comptes-consolides.pdf",
     "Reglement ANC 2020-01 relatif aux comptes consolides (version 2026)",
     "https://www.anc.gouv.fr/files/anc/files/1_Normes_fran%C3%A7aises/recueil/REGLT-2020_01-VERSION-RECUEIL2026.pdf"),
]

BRUIT = [   # lignes entieres d'en-tete / de pied de page, a supprimer
    re.compile(r"^\s*Version (?:du )?1er janvier 2026\b.*$"),
    re.compile(r"^\s*R[eè]glement ANC n°\s?[\d-]+ (?:consolid[eé] )?au 1er janvier 2026\b.*$"),
    re.compile(r"^\s*RECUEIL DES NORMES COMPTABLES\b.*$"),
]
RE_ART = re.compile(r"^\s*Art\.\s?(\d+(?:-\s?\d+)*(?:/\d+)?)(?![\d])[ \t]*(.*)$")
NIVEAUX = [
    ("livre", re.compile(r"^\s*(Livre|LIVRE)\s+[IVX\d]+\b.*")),
    ("titre", re.compile(r"^\s*(Titre|TITRE)\s+[IVXL\d]+\b.*")),
    ("chapitre", re.compile(r"^\s*(Chapitre|CHAPITRE)\s+[IVXL\d]+\b.*")),
    ("section", re.compile(r"^\s*(Section|SECTION)\s+\d+\b.*")),
    ("sous", re.compile(r"^\s*(Sous-section|SOUS-SECTION)\s+\d+\b.*")),
    ("para", re.compile(r"^\s*(Paragraphe|PARAGRAPHE)\s+\d+\b.*")),
]
RE_TOC = re.compile(r"\.{4,}\s*\d+\s*$")
RE_COMPTE = re.compile(r"^\s*\d{2,6}\s+\S")


def pages_de(pdf):
    sortie = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, check=True).stdout
    return sortie.decode("utf-8", "replace").split("\f")


def nettoyer_ligne(l):
    """Ligne nettoyee, ou None si c'est un en-tete / pied de page."""
    if any(rx.match(l) for rx in BRUIT):
        return None
    return l.rstrip()


def reflow(lignes):
    """Rejoint les lignes d'un meme paragraphe ; conserve les lignes de tableaux (plan de comptes)."""
    sortie = []
    for l in lignes:
        brut = l.rstrip()
        if not brut.strip():
            sortie.append("")
            continue
        est_compte = bool(RE_COMPTE.match(brut))
        txt = brut if est_compte else brut.strip()
        if sortie and sortie[-1] and not est_compte and not RE_COMPTE.match(sortie[-1]):
            prec = sortie[-1]
            nouvelle_puce = re.match(r"^([•\-–·o]|\d+[°)\.]|[a-z]\)|\(?[ivx]+\))\s", txt) is not None
            if len(prec) >= 80 and not prec.endswith((".", ";", ":", "?")) and not nouvelle_puce:
                sortie[-1] = prec + " " + txt
                continue
        sortie.append(txt)
    # supprime les blancs multiples
    res, vide = [], False
    for l in sortie:
        if not l:
            if not vide:
                res.append("")
            vide = True
        else:
            res.append(l)
            vide = False
    return "\n".join(res).strip()


def decouper(texte, maxi=1500):
    paras = [p for p in texte.split("\n")]
    passages, cur = [], ""
    for p in paras:
        while len(p) > maxi:
            coupe = p.rfind(" ", 0, maxi)
            coupe = coupe if coupe > 200 else maxi
            if cur:
                passages.append(cur)
                cur = ""
            passages.append(p[:coupe])
            p = p[coupe:].lstrip()
        if cur and len(cur) + len(p) + 1 > maxi:
            passages.append(cur)
            cur = p
        else:
            cur = (cur + "\n" + p) if cur else p
    if cur.strip():
        passages.append(cur)
    return [x.strip() for x in passages if x.strip()]


def analyser(code, pdf):
    pages = pages_de(pdf)
    articles = []          # dict(num, titre, chemin, page, lignes)
    chemin = {}
    courant = None
    corps = False          # on ignore le sommaire jusqu'au premier article
    for n_page, page in enumerate(pages, 1):
        for brute in page.split("\n"):
            l = nettoyer_ligne(brute)
            if l is None:
                continue
            if not l.strip():
                if courant is not None:
                    courant["lignes"].append("")
                continue
            if RE_TOC.search(l):
                continue
            m = RE_ART.match(l)
            if m and not RE_TOC.search(l):
                corps = True
                if courant is not None:
                    articles.append(courant)
                courant = {"num": re.sub(r"\s+", "", m.group(1)), "titre": m.group(2).strip(" ,;:-–"), "page": n_page,
                           "chemin": " > ".join(chemin[k] for k, _ in NIVEAUX if k in chemin),
                           "lignes": []}
                continue
            if corps:
                niveau = next((k for k, rx in NIVEAUX if rx.match(l) and len(l.strip()) < 160), None)
                if niveau:
                    if courant is not None:
                        articles.append(courant)
                        courant = None
                    ordre = [k for k, _ in NIVEAUX]
                    for k in ordre[ordre.index(niveau):]:
                        chemin.pop(k, None)
                    chemin[niveau] = re.sub(r"\s+", " ", l.strip())
                    continue
            if courant is not None:
                courant["lignes"].append(l)
    if courant is not None:
        articles.append(courant)
    return articles


SCHEMA = """
CREATE TABLE docs(id TEXT PRIMARY KEY, source TEXT, type TEXT, serie TEXT, division TEXT,
  titre TEXT, debut TEXT, url TEXT, nb INTEGER);
CREATE TABLE chunks(id INTEGER PRIMARY KEY, doc TEXT, n INTEGER, par TEXT, titre TEXT, texte TEXT);
CREATE INDEX chunks_doc ON chunks(doc, n);
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
CREATE VIRTUAL TABLE fts USING fts5(titre, texte, content='chunks', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2');
"""


def main(dossier, sortie):
    if os.path.exists(sortie):
        os.remove(sortie)
    con = sqlite3.connect(sortie)
    con.executescript(SCHEMA)
    total_docs = total_chunks = 0
    detail = []
    for code, fichier, libelle, url in SOURCES:
        arts = analyser(code, os.path.join(dossier, fichier))
        n_docs = 0
        vus = set()
        for a in arts:
            texte = reflow(a["lignes"])
            titre_art = a["titre"]
            if re.match(r"(?i)^abrog", titre_art) or (len(texte) < 25 and not titre_art) or re.fullmatch(r"(?i)\(?abrog[ée]e?\)?\.?", texte or ""):
                continue
            if len(texte) < 12:
                continue
            ident = f"{code} art. {a['num']}"
            if ident in vus:   # meme numero repete (ex. reglements successifs) : on suffixe
                k = 2
                while f"{ident} ({k})" in vus:
                    k += 1
                ident = f"{ident} ({k})"
            vus.add(ident)
            court = " > ".join(a["chemin"].split(" > ")[-3:]) if a["chemin"] else ""
            titre = " — ".join(x for x in (f"Art. {a['num']}", titre_art, court) if x)
            passages = decouper(texte)
            con.execute("INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?)",
                        (ident, "ANC", "Contenu", code, a["chemin"], titre, "2026-01-01",
                         f"{url}#page={a['page']}", len(passages)))
            for i, p in enumerate(passages, 1):
                con.execute("INSERT INTO chunks(doc,n,par,titre,texte) VALUES (?,?,?,?,?)",
                            (ident, i, a["num"], titre, p))
                total_chunks += 1
            n_docs += 1
        detail.append(f"{code} {n_docs}")
        total_docs += n_docs
        print(f"{code}: {len(arts)} blocs, {n_docs} articles indexes")
    con.execute("INSERT INTO fts(rowid,titre,texte) SELECT id,titre,texte FROM chunks")
    con.execute("INSERT INTO fts(fts) VALUES('optimize')")
    for k, v in (("normes_construit_le", time.strftime("%Y-%m-%d %H:%M")),
                 ("normes_articles", str(total_docs)), ("normes_passages", str(total_chunks)),
                 ("normes_detail", ", ".join(detail)), ("normes_version", "1er janvier 2026"),
                 ("normes_sources", " | ".join(f"{c}: {l}" for c, _, l, _ in SOURCES))):
        con.execute("INSERT INTO meta VALUES (?,?)", (k, v))
    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"{total_docs} articles, {total_chunks} passages, {os.path.getsize(sortie) / 1e6:.1f} Mo")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
