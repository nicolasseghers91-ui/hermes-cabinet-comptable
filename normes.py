# -*- coding: utf-8 -*-
"""
Normes comptables francaises (ANC) : recherche dans normes.sqlite.

Sources indexees (version consolidee au 1er janvier 2026) :
  PCG     reglement ANC 2014-03 (Plan comptable general) - texte reglementaire
  RECUEIL recueil des normes comptables des entreprises (PCG + commentaires de doctrine)
  ASSO    reglement ANC 2018-06 (associations et fondations)
  CONSO   reglement ANC 2020-01 (comptes consolides)

La base est produite par build_normes.py (avec pdftotext) puis copiee a cote du serveur.
"""
import os
import re
import sqlite3

import doctrine_mcp as dm

DB = os.path.join(dm.ICI, "normes.sqlite")
MAX_EXTRAIT = 650
MAX_LECTURE = 3200

PRIORITE = ["PCG", "RECUEIL", "ASSO", "CONSO"]
ALIAS = {
    "pcg": "PCG", "plan comptable general": "PCG", "plan comptable": "PCG", "anc 2014-03": "PCG",
    "recueil": "RECUEIL", "commentaires": "RECUEIL", "doctrine": "RECUEIL",
    "asso": "ASSO", "association": "ASSO", "associations": "ASSO", "fondation": "ASSO",
    "non lucratif": "ASSO", "anc 2018-06": "ASSO",
    "conso": "CONSO", "consolide": "CONSO", "consolides": "CONSO", "comptes consolides": "CONSO",
    "anc 2020-01": "CONSO",
}
RE_NUM = re.compile(r"(?<![\d-])(\d{3,4}-\d+(?:/\d+)?)(?![\d])")


def ouvrir():
    if not os.path.exists(DB):
        raise RuntimeError("Les normes comptables ne sont pas installees : le fichier normes.sqlite "
                           "manque dans le dossier du serveur.")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def code_source(valeur):
    if not valeur:
        return None
    v = dm.sans_accents(str(valeur).strip().lower())
    if not v or v in ("null", "none", "tous", "toutes", "all"):
        return None
    if v.upper() in PRIORITE:
        return v.upper()
    return ALIAS.get(v)


def durees(texte):
    res = []
    for m in re.finditer(r"(\d+)\s*(ans?|années?|annees?|mois)\b", (texte or "").lower()):
        res.append(f"{int(m.group(1))} {'mois' if m.group(2) == 'mois' else 'ans'}")
    return res


def verifier_durees(requete, extraits):
    """Si la question cite une duree (« 20 ans ») absente de tous les extraits, previent le modele."""
    demandes = list(dict.fromkeys(durees(requete)))
    if not demandes:
        return ""
    trouvees = list(dict.fromkeys(d for e in extraits for d in durees(e)))
    absentes = [d for d in demandes if d not in trouvees]
    if not absentes:
        return ""
    liste = ", ".join(trouvees[:6]) if trouvees else "aucune duree"
    return ("\nATTENTION : " + ", ".join(absentes) + " de la question n'apparait dans aucun passage ci-dessus "
            f"(durees trouvees : {liste}). Ne reprends pas ce chiffre comme exact : dis a l'utilisateur "
            "que les passages ne le confirment pas et cite ceux qui s'appliquent.")


def empreinte(texte):
    return " ".join(dm.mots_normalises(texte))[:160]


def par_numero(con, requete, source):
    """Articles dont le numero est cite dans la requete (« article 214-3 »)."""
    trouves = []
    for num in dict.fromkeys(RE_NUM.findall(requete or "")):
        sql = "SELECT * FROM docs WHERE (id LIKE ? OR id LIKE ?)"
        p = [f"% art. {num}", f"% art. {num} (%"]
        if source:
            sql += " AND serie = ?"
            p.append(source)
        lignes = con.execute(sql, p).fetchall()
        lignes.sort(key=lambda d: (PRIORITE.index(d["serie"]), d["id"]))
        trouves += lignes
    return trouves


def chercher(requete, source=None, limite=3):
    con = ouvrir()
    limite = dm.entier(limite, 3, 1, 4)
    src = code_source(source)
    numeros = RE_NUM.findall(requete or "")
    mots = dm.jetons(RE_NUM.sub(" ", requete or ""))
    mots = [m for m in mots if m not in ("article", "articles", "art", "pcg", "anc", "reglement")]
    if not mots and not numeros:
        con.close()
        return "Requete vide : donne quelques mots-cles (ex. « amortissement fonds commercial »)."
    racines = [dm.racine(m) for m in mots]

    resultats = []
    # 1. articles cites par leur numero
    for d in par_numero(con, requete, src)[:3]:
        n = con.execute("SELECT n, par, texte FROM chunks WHERE doc=? ORDER BY n LIMIT 1", (d["id"],)).fetchone()
        resultats.append((1000, d, (0, n["n"], n["par"], n["texte"]), []))
    # 2. recherche par mots-cles
    if mots:
        docs = dm.candidats_fts(con, mots, src, None, False, 30, max(limite * 4, 12))
        notes = dm.noter_documents(con, docs, racines)
        notes = [(sc + (6 if d["serie"] == "PCG" else 0), d, m, a) for sc, d, m, a in notes]
        notes.sort(key=lambda x: -x[0])
        resultats += notes
    if not resultats:
        con.close()
        return ("Aucun resultat. Essaie d'autres mots-cles, ou un numero d'article du PCG "
                "(ex. « 214-3 », « 1121-1 »).")

    sorties, extraits, vus_id, vus_texte = [], [], set(), set()
    for score, d, (sc, n, par, texte), autres in resultats:
        if d["id"] in vus_id:
            continue
        emp = empreinte(texte)
        if emp in vus_texte:   # meme texte deja renvoye (PCG repris dans le recueil)
            continue
        vus_id.add(d["id"])
        vus_texte.add(emp)
        i = len(sorties) + 1
        ext = dm.extrait(texte, racines, MAX_EXTRAIT if limite <= 3 else 480) if racines else texte[:MAX_EXTRAIT]
        extraits.append(ext)
        bloc = (f"[{i}] {d['id']} (passage {n}/{d['nb']})\n{d['titre']}\n"
                f"{d['url']}\n{ext}")
        if autres:
            bloc += f"\n(autres passages pertinents : {', '.join(map(str, autres))})"
        sorties.append(bloc)
        if len(sorties) >= limite:
            break
    pied = (dm.verifier_chiffres(requete, extraits) + verifier_durees(requete, extraits)
            + f"\n---\nNormes comptables ANC, version du {dm.meta(con, 'normes_version', '1er janvier 2026')}. "
            "PCG = texte reglementaire ; RECUEIL = PCG + commentaires de doctrine ; ASSO = associations ; "
            "CONSO = comptes consolides. Verifie que ces passages confirment ce que dit l'utilisateur ; "
            "sinon, dis-le. Cite uniquement ces articles. Suite : lire_norme(identifiant, passage).")
    con.close()
    return "\n\n".join(sorties) + pied


def resoudre(con, ident):
    """« PCG art. 214-3 », « 214-3 », « art. 214-3 asso » -> ligne de docs (ou liste de propositions)."""
    ident = (ident or "").strip()
    d = con.execute("SELECT * FROM docs WHERE upper(id)=upper(?)", (ident,)).fetchone()
    if d:
        return d, []
    m = RE_NUM.search(ident) or re.search(r"(?<![\d-])(\d{3,4})(?![\d-])", ident)
    if not m:
        return None, con.execute("SELECT * FROM docs WHERE upper(id) LIKE upper(?) ORDER BY id LIMIT 12",
                                 (ident + "%",)).fetchall()
    num = m.group(1)
    lignes = con.execute("SELECT * FROM docs WHERE id LIKE ? OR id LIKE ?",
                         (f"% art. {num}", f"% art. {num} (%")).fetchall()
    src = code_source(next((w for w in re.findall(r"[A-Za-z]+", ident) if code_source(w)), None))
    if src:
        lignes = [x for x in lignes if x["serie"] == src] or lignes
    lignes.sort(key=lambda x: (PRIORITE.index(x["serie"]), x["id"]))
    if not lignes:
        return None, []
    return lignes[0], lignes[1:]


def lire(identifiant, passage=1, nombre=2):
    con = ouvrir()
    d, autres = resoudre(con, identifiant)
    if not d:
        con.close()
        if not autres:
            return f"Aucun article ne correspond a « {identifiant} »."
        return "Identifiants proches :\n" + "\n".join(f"- {v['id']} : {v['titre'][:110]}" for v in autres)
    passage = dm.entier(passage, 1, 1, 10000)
    nombre = dm.entier(nombre, 2, 1, 3)
    rows = con.execute("SELECT n, texte FROM chunks WHERE doc=? AND n>=? AND n<? ORDER BY n",
                       (d["id"], passage, passage + nombre)).fetchall()
    con.close()
    if not rows:
        return f"{d['id']} n'a que {d['nb']} passages."
    corps, taille, dernier = [], 0, passage - 1
    for r in rows:
        bloc = f"(passage {r['n']}/{d['nb']})\n{r['texte']}"
        if corps and taille + len(bloc) > MAX_LECTURE:
            break
        corps.append(bloc)
        taille += len(bloc)
        dernier = r["n"]
    suite = f"\n\n[Suite : lire_norme(\"{d['id']}\", passage={dernier + 1})]" if dernier < d["nb"] else ""
    ailleurs = ""
    if autres:
        ailleurs = "\n\n[Meme numero dans d'autres sources : " + ", ".join(a["id"] for a in autres[:4]) + "]"
    return f"{d['serie']} {d['titre']}\n{d['url']}\n\n" + "\n\n".join(corps) + suite + ailleurs


def info():
    try:
        con = ouvrir()
        s = (f"Normes comptables : {dm.meta(con, 'normes_articles')} articles, "
             f"{dm.meta(con, 'normes_passages')} passages ({dm.meta(con, 'normes_detail')}), "
             f"construit le {dm.meta(con, 'normes_construit_le')}")
        con.close()
        return s
    except Exception as e:  # noqa: BLE001
        return f"Normes comptables : non disponibles ({e})"
