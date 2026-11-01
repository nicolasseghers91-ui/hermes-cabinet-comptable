# -*- coding: utf-8 -*-
"""
Codes et lois consolides (base LEGI de la DILA) pour doctrine-mcp.

  python doctrine_mcp.py construire-lois     telecharge / met a jour les codes puis reconstruit l'index
  python doctrine_mcp.py loi "texte" [CODE]  recherche
  python doctrine_mcp.py article CGI 279     lit un article

Source : base LEGI (DILA), Licence Ouverte v2.0 (Etalab) - https://echanges.dila.gouv.fr/OPENDATA/LEGI/
Premier passage : archive complete (~1,1 Go) puis mises a jour quotidiennes ; ensuite seules les
mises a jour manquantes sont telechargees.
"""
import io
import os
import re
import sqlite3
import sys
import tarfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

BASE_LEGI = "https://echanges.dila.gouv.fr/OPENDATA/LEGI/"

CODES = {  # abreviation: (identifiant LEGITEXT, nom)
    "CGI": ("LEGITEXT000006069577", "Code général des impôts"),
    "LPF": ("LEGITEXT000006069583", "Livre des procédures fiscales"),
    "COM": ("LEGITEXT000005634379", "Code de commerce"),
    "CIV": ("LEGITEXT000006070721", "Code civil"),
    "CMF": ("LEGITEXT000006072026", "Code monétaire et financier"),
    "CIBS": ("LEGITEXT000044595989", "Code des impositions sur les biens et services"),
    "CT": ("LEGITEXT000006072050", "Code du travail"),
    "CSS": ("LEGITEXT000006073189", "Code de la sécurité sociale"),
}
PAR_CID = {v[0]: k for k, v in CODES.items()}

# formes acceptees pour designer un code (sans accents, minuscules)
ALIAS = {
    "cgi": "CGI", "code general des impots": "CGI", "impots": "CGI",
    "lpf": "LPF", "livre des procedures fiscales": "LPF",
    "com": "COM", "c. com": "COM", "code de commerce": "COM", "commerce": "COM",
    "civ": "CIV", "c. civ": "CIV", "code civil": "CIV", "civil": "CIV",
    "cibs": "CIBS", "code des impositions sur les biens et services": "CIBS",
    "cmf": "CMF", "code monetaire et financier": "CMF", "code monetaire": "CMF", "monetaire": "CMF",
    "ct": "CT", "c. trav": "CT", "code du travail": "CT",
    "css": "CSS", "c. secu. soc": "CSS", "code de la securite sociale": "CSS",
}

ETATS_UTILES = {"VIGUEUR", "VIGUEUR_DIFF", "ABROGE_DIFF"}
FIN_OUVERTE = "2999-01-01"
MAX_EXTRAIT = 650
POIDS = {"dist": 8.0, "tf": 0.3, "rang": 40.0, "taille": 4.0}
MAX_PAGE = 3000


def _dm():
    import doctrine_mcp as dm
    return dm


def chemin_db():
    return os.path.join(_dm().ICI, "legislation.sqlite")


def log(*a):
    _dm().log(*a)


# --------------------------------------------------------------------------- lecture du XML LEGI

BLOCS = {"p", "br", "li", "ul", "ol", "div", "tr", "table", "blockquote",
         "h1", "h2", "h3", "h4", "h5", "h6"}


def texte_de(elem):
    morceaux = []

    def rec(e):
        tag = e.tag.lower() if isinstance(e.tag, str) else ""
        if tag in BLOCS:
            morceaux.append("\n")
        elif tag in ("td", "th"):
            morceaux.append(" | ")
        if e.text:
            morceaux.append(e.text)
        for c in e:
            rec(c)
            if c.tail:
                morceaux.append(c.tail)
        if tag in BLOCS:
            morceaux.append("\n")

    rec(elem)
    lignes = [re.sub(r"[ \t ]+", " ", l).strip(" |") .strip() for l in "".join(morceaux).split("\n")]
    return "\n".join(l for l in lignes if l)


RE_ENTITE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)([A-Za-z][A-Za-z0-9]*);")


def _entite(m):
    import html.entities
    cp = html.entities.name2codepoint.get(m.group(1))
    return chr(cp) if cp else " "


def lire_article_xml(donnees):
    try:
        racine = ET.fromstring(donnees)
    except ET.ParseError:
        try:  # entites HTML nommees (&nbsp; ...) non declarees en XML
            racine = ET.fromstring(RE_ENTITE.sub(_entite, donnees.decode("utf-8", "replace")).encode("utf-8"))
        except ET.ParseError:
            return None
    if racine.tag != "ARTICLE":
        return None
    meta = racine.find("META/META_SPEC/META_ARTICLE")
    ident = (racine.findtext("META/META_COMMUN/ID") or "").strip()
    if meta is None or not ident:
        return None
    ctx = racine.find("CONTEXTE/TEXTE")
    titres = []
    if ctx is not None:
        for t in ctx.iter("TITRE_TM"):
            if (t.text or "").strip():
                titres.append(re.sub(r"\s+", " ", t.text).strip())
    bloc = racine.find("BLOC_TEXTUEL/CONTENU")
    return {
        "id": ident,
        "num": (meta.findtext("NUM") or "").strip(),
        "etat": (meta.findtext("ETAT") or "").strip(),
        "debut": (meta.findtext("DATE_DEBUT") or "").strip(),
        "fin": (meta.findtext("DATE_FIN") or "").strip() or FIN_OUVERTE,
        "chemin": " > ".join(titres),
        "texte": texte_de(bloc) if bloc is not None else "",
    }


# --------------------------------------------------------------------------- base de travail

SCHEMA_STAGE = """
CREATE TABLE IF NOT EXISTS stage(
  id TEXT PRIMARY KEY, code TEXT, num TEXT, debut TEXT, fin TEXT, chemin TEXT, texte TEXT);
CREATE TABLE IF NOT EXISTS etat(k TEXT PRIMARY KEY, v TEXT);
"""

RE_CHEMIN = re.compile(r"/code_(?:en|non)_vigueur/LEGI/TEXT/(?:\d\d/)+(LEGITEXT\d+)/article/")


def code_du_chemin(nom, avec_non_vigueur=True):
    m = RE_CHEMIN.search("/" + nom)
    if not m or m.group(1) not in PAR_CID:
        return None
    if not avec_non_vigueur and "/code_non_vigueur/" in nom:
        return None
    return PAR_CID[m.group(1)]


def integrer(con, donnees, code):
    a = lire_article_xml(donnees)
    if not a:
        return 0
    if a["etat"] in ETATS_UTILES and a["texte"]:
        con.execute("INSERT OR REPLACE INTO stage VALUES (?,?,?,?,?,?,?)",
                    (a["id"], code, a["num"], a["debut"], a["fin"], a["chemin"], a["texte"]))
        return 1
    con.execute("DELETE FROM stage WHERE id=?", (a["id"],))
    return 0


def lire_archive(con, tar, avec_non_vigueur, progression=False):
    """Traite une archive (flux tar deja ouvert). Renvoie (articles gardes, supprimes)."""
    gardes = supprimes = vus = lus = 0
    for m in tar:
        tar.members = []  # evite de garder en memoire les millions d'entrees deja lues
        lus += 1
        if progression and lus % 200000 == 0:
            log(f"  {lus // 1000} 000 fichiers parcourus, {gardes} articles retenus")
        if not m.isfile():
            continue
        nom = m.name
        if nom.endswith("liste_suppression_legi.dat"):
            for ligne in tar.extractfile(m).read().decode("utf-8", "replace").splitlines():
                ident = ligne.strip().rsplit("/", 1)[-1]
                if ident.startswith("LEGIARTI"):
                    supprimes += con.execute("DELETE FROM stage WHERE id=?", (ident,)).rowcount
            continue
        code = code_du_chemin(nom, avec_non_vigueur)
        if not code:
            continue
        gardes += integrer(con, tar.extractfile(m).read(), code)
        vus += 1
        if vus % 4000 == 0:
            con.commit()
    return gardes, supprimes


# --------------------------------------------------------------------------- acces aux archives

RE_ARCHIVE = re.compile(r'href="((?:Freemium_legi_global|LEGI)_(\d{8}-\d{6})\.tar\.gz)"')


def lister(base):
    """[(nom, 'AAAAMMJJ-HHMMSS', est_global)] trie par date."""
    if base.startswith("http"):
        req = urllib.request.Request(base, headers={"User-Agent": "doctrine-mcp"})
        with urllib.request.urlopen(req, timeout=120) as r:
            html = r.read().decode("utf-8", "replace")
        noms = [(m.group(1), m.group(2)) for m in RE_ARCHIVE.finditer(html)]
    else:
        noms = []
        for f in os.listdir(base):
            m = re.match(r"(?:Freemium_legi_global|LEGI)_(\d{8}-\d{6})\.tar\.gz$", f)
            if m:
                noms.append((f, m.group(1)))
    return sorted(((n, s, n.startswith("Freemium")) for n, s in set(noms)), key=lambda x: x[1])


def octets(base, nom):
    if base.startswith("http"):
        for essai in range(1, 4):
            try:
                req = urllib.request.Request(base + nom, headers={"User-Agent": "doctrine-mcp"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    return r.read()
            except Exception as e:  # noqa: BLE001
                log(f"  echec {nom} (essai {essai}/3) : {e}")
                time.sleep(3 * essai)
        raise RuntimeError(f"Telechargement impossible : {nom}")
    with open(os.path.join(base, nom), "rb") as f:
        return f.read()


def telecharger_reprise(url, destination):
    """Telechargement avec reprise (fichier .part conserve en cas d'interruption)."""
    tmp = destination + ".part"
    for essai in range(1, 7):
        try:
            debut = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            entetes = {"User-Agent": "doctrine-mcp"}
            if debut:
                entetes["Range"] = f"bytes={debut}-"
                log(f"  reprise du telechargement a {debut / 1e6:.0f} Mo")
            req = urllib.request.Request(url, headers=entetes)
            try:
                r = urllib.request.urlopen(req, timeout=120)
            except urllib.error.HTTPError as e:
                if e.code == 416 and debut:  # deja complet
                    os.replace(tmp, destination)
                    return
                raise
            with r:
                mode = "ab" if (debut and r.status == 206) else "wb"
                total, dernier, t0 = (debut if mode == "ab" else 0), 0, time.time()
                with open(tmp, mode) as f:
                    while True:
                        bloc = r.read(1 << 20)
                        if not bloc:
                            break
                        f.write(bloc)
                        total += len(bloc)
                        if time.time() - dernier > 5:
                            dernier = time.time()
                            log(f"  telecharge : {total / 1e6:.0f} Mo")
            os.replace(tmp, destination)
            log(f"  telechargement termine : {total / 1e6:.0f} Mo ({time.time() - t0:.0f} s)")
            return
        except Exception as e:  # noqa: BLE001
            log(f"  interruption (essai {essai}/6) : {e}")
            time.sleep(5 * essai)
    raise RuntimeError("Telechargement impossible : relancer le fichier .bat (la reprise est automatique).")


def fichier_global(base, nom, dossier):
    if not base.startswith("http"):
        return os.path.join(base, nom), False
    destination = os.path.join(dossier, nom)
    if not os.path.exists(destination):
        log(f"Telechargement de l'archive complete ({nom}, ~1,1 Go) : compter 10 a 30 minutes.")
        telecharger_reprise(base + nom, destination)
    else:
        log(f"Archive complete deja telechargee : {nom}")
    return destination, True


# --------------------------------------------------------------------------- indexation

SCHEMA_INDEX = """
DROP TABLE IF EXISTS afts;
DROP TABLE IF EXISTS arts;
CREATE TABLE arts(
  id INTEGER PRIMARY KEY, legi TEXT, code TEXT, num TEXT, numn TEXT, debut TEXT, fin TEXT,
  avenir TEXT, chemin TEXT, titre TEXT, texte TEXT);
CREATE INDEX arts_num ON arts(code, numn);
CREATE VIRTUAL TABLE afts USING fts5(
  titre, texte, content='arts', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
"""


def norm_num(n):
    return re.sub(r"[\s\.]+", "", (n or "").lower())


def indexer(con):
    aujourdhui = time.strftime("%Y-%m-%d")
    con.executescript(SCHEMA_INDEX)
    en_vigueur, avenir = {}, {}
    for (legi, code, num, debut, fin, chemin, texte) in con.execute(
            "SELECT id,code,num,debut,fin,chemin,texte FROM stage"):
        cle = (code, norm_num(num))
        if debut <= aujourdhui < fin:
            if cle not in en_vigueur or debut > en_vigueur[cle][3]:
                en_vigueur[cle] = (legi, code, num, debut, fin, chemin, texte)
        elif debut > aujourdhui:
            if cle not in avenir or debut < avenir[cle]:
                avenir[cle] = debut
    lignes = []
    for cle, (legi, code, num, debut, fin, chemin, texte) in sorted(en_vigueur.items()):
        niveaux = [t for t in chemin.split(" > ") if not t.lower().startswith(("partie ", "livre "))] or [chemin]
        titre = f"{CODES[code][1]} article {num} " + " ".join(niveaux)
        lignes.append((legi, code, num, cle[1], debut, fin, avenir.get(cle, ""), chemin, titre, texte))
    con.executemany(
        "INSERT INTO arts(legi,code,num,numn,debut,fin,avenir,chemin,titre,texte) VALUES (?,?,?,?,?,?,?,?,?,?)",
        lignes)
    con.execute("INSERT INTO afts(rowid,titre,texte) SELECT id,titre,texte FROM arts")
    con.execute("INSERT INTO afts(afts) VALUES('optimize')")
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    par_code = dict(con.execute("SELECT code, COUNT(*) FROM arts GROUP BY code").fetchall())
    for k, v in (("lois_construit_le", time.strftime("%Y-%m-%d %H:%M")),
                 ("lois_articles", str(len(lignes))),
                 ("lois_detail", ", ".join(f"{c} {n}" for c, n in sorted(par_code.items())))):
        con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))
    con.commit()
    return len(lignes), par_code


def construire(args):
    base = BASE_LEGI
    if "--source" in args:
        base = args[args.index("--source") + 1]
        if base.startswith("http") and not base.endswith("/"):
            base += "/"
    dossier = os.path.join(_dm().DOSSIER_DONNEES, "legi")
    os.makedirs(dossier, exist_ok=True)
    db = chemin_db()
    con = sqlite3.connect(db)
    con.executescript(SCHEMA_STAGE)
    etat = dict(con.execute("SELECT k, v FROM etat").fetchall())
    t0 = time.time()
    codes_actuels = ",".join(sorted(CODES))
    if "dernier" in etat and etat.get("codes", "CGI,CIV,CMF,COM,LPF") != codes_actuels:
        log("La liste des codes a change : relecture de l'archive complete.")
        con.execute("DELETE FROM stage")
        con.execute("DELETE FROM etat")
        con.commit()
        etat = {}

    archives = lister(base)
    globaux = [a for a in archives if a[2]]
    if "dernier" not in etat:
        if not globaux:
            raise RuntimeError("Aucune archive complete trouvee dans " + base)
        nom, stamp, _ = globaux[-1]
        chemin, a_supprimer = fichier_global(base, nom, dossier)
        log(f"Lecture de l'archive complete {nom} (5 a 15 minutes)…")
        with open(chemin, "rb") as f, tarfile.open(fileobj=f, mode="r|gz") as tar:
            g, _ = lire_archive(con, tar, avec_non_vigueur=False, progression=True)
        con.execute("INSERT OR REPLACE INTO etat VALUES ('dernier', ?)", (stamp,))
        con.execute("INSERT OR REPLACE INTO etat VALUES ('codes', ?)", (codes_actuels,))
        con.commit()
        etat["dernier"] = stamp
        log(f"  {g} versions d'articles retenues ({time.time() - t0:.0f} s)")
        if a_supprimer:
            log("Archive conservee dans donnees\\legi (evite un nouveau telechargement si un code est ajoute) ; "
                "tu peux supprimer ce dossier pour liberer ~1,1 Go.")

    suivantes = [a for a in archives if not a[2] and a[1] > etat["dernier"]]
    log(f"{len(suivantes)} mise(s) a jour quotidienne(s) a appliquer.")
    for i, (nom, stamp, _) in enumerate(suivantes, 1):
        brut = octets(base, nom)
        with tarfile.open(fileobj=io.BytesIO(brut), mode="r:gz") as tar:
            lire_archive(con, tar, avec_non_vigueur=True)
        con.execute("INSERT OR REPLACE INTO etat VALUES ('dernier', ?)", (stamp,))
        con.commit()
        if i % 20 == 0 or i == len(suivantes):
            log(f"  mises a jour : {i}/{len(suivantes)} ({time.time() - t0:.0f} s)")

    log("Indexation…")
    n, par_code = indexer(con)
    con.execute("VACUUM")
    con.close()
    log(f"Termine : {n} articles en vigueur ({', '.join(f'{c} {k}' for c, k in sorted(par_code.items()))}) "
        f"- {os.path.getsize(db) / 1e6:.0f} Mo - {time.time() - t0:.0f} s")


# --------------------------------------------------------------------------- recherche

def ouvrir():
    db = chemin_db()
    if not os.path.exists(db):
        raise RuntimeError("L'index des codes n'existe pas encore : lancer « construire_lois.bat ».")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("SELECT 1 FROM arts LIMIT 1")
    except sqlite3.OperationalError:
        con.close()
        raise RuntimeError("L'index des codes est incomplet : relancer « construire_lois.bat ».")
    return con


def meta(con, cle):
    r = con.execute("SELECT v FROM meta WHERE k=?", (cle,)).fetchone()
    return r[0] if r else ""


def code_de(texte):
    """Code designe par un texte libre (parametre « code » ou mention dans la question)."""
    dm = _dm()
    t = " " + dm.sans_accents((texte or "").lower()) + " "
    for alias in sorted(ALIAS, key=len, reverse=True):
        if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", t):
            return ALIAS[alias]
    return None


SUFFIXES = (r"bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies|undecies|duodecies|terdecies|"
            r"quaterdecies|quindecies|sexdecies|septdecies|octodecies|novodecies|vicies")
NUM = (r"(?:[LRD]\s*\.?\s*)?\d+(?:\s*-\s*\d+)*"
       r"(?:\s+(?:" + SUFFIXES + r")(?:\s+[A-Z]{1,2}\b)?)?(?:\s+[A-Z]\b)?")
RE_NUM_ART = re.compile(r"\b(?:articles?|art)\b\.?\s*(" + NUM + ")", re.I)
RE_NUM_NU = re.compile(r"\b([LRD]\s*\.?\s*\d{1,4}(?:\s*-\s*\d+)+(?:\s+(?:" + SUFFIXES + r"))?)\b", re.I)


def numeros_cites(requete):
    res = []
    for rx in (RE_NUM_ART, RE_NUM_NU):
        for m in rx.finditer(requete or ""):
            brut = m.group(1)
            n = norm_num(brut)
            variantes = [n]
            # « 279 a » : lettre isolee finale -> « 279a » puis « 279 »
            mots = brut.split()
            if len(mots) > 1 and re.fullmatch(r"[A-Za-z]{1,2}", mots[-1]):
                variantes.append(norm_num(" ".join(mots[:-1])))
            for v in variantes:
                if v and v not in res:
                    res.append(v)
    return res


# abreviations courantes -> mots du texte de loi (tous requis ensemble)
SYNONYMES = {
    "tva": ["taxe", "valeur", "ajoutee"], "sarl": ["responsabilite", "limitee"], "eurl": ["responsabilite", "limitee"],
    "sas": ["actions", "simplifiee"], "sasu": ["actions", "simplifiee"], "sca": ["commandite", "actions"],
    "snc": ["nom", "collectif"], "sci": ["societe", "civile"], "bic": ["benefices", "industriels", "commerciaux"],
    "bnc": ["benefices", "non", "commerciaux"], "cac": ["commissaires", "comptes"],
    "rcs": ["registre", "commerce", "societes"], "cvae": ["cotisation", "valeur", "ajoutee"],
    "cfe": ["cotisation", "fonciere", "entreprises"], "ago": ["assemblee", "generale"],
    "cession": ["cede"], "cessions": ["cede"], "ceder": ["cede"],
    "cdd": ["duree", "determinee"], "cdi": ["duree", "indeterminee"],
    "cse": ["comite", "social", "economique"], "csg": ["contribution", "sociale", "generalisee"],
    "crds": ["remboursement", "dette", "sociale"], "pass": ["plafond", "securite", "sociale"],
}


def groupes_de(mots):
    """[[alternative, ...], ...] ; une alternative = liste de racines requises ensemble."""
    dm = _dm()
    res = []
    for m in mots:
        g = [[dm.racine(m)]]
        if m in SYNONYMES:
            g.append([dm.racine(w) for w in SYNONYMES[m]])
        res.append(g)
    return res


def _terme(r):
    return f'"{r}"*' if (len(r) >= 4 and not r.isdigit()) else f'"{r}"'


def requete_groupes(groupes, mode):
    parts = []
    for g in groupes:
        alts = []
        for alt in g:
            e = " AND ".join(_terme(r) for r in alt)
            alts.append(f"({e})" if len(alt) > 1 else e)
        parts.append("(" + " OR ".join(alts) + ")" if len(alts) > 1 else alts[0])
    return (" OR " if mode == "ou" else " AND ").join(parts)


def couverture_groupes(groupes, mots_norm):
    """(groupes satisfaits, occurrences plafonnees) sur une liste de mots normalises."""
    dist, tot = 0, 0.0
    for g in groupes:
        meilleur = 0
        for alt in g:
            n = 0
            ok = True
            for r in alt:
                if len(r) >= 4 and not r.isdigit():
                    c = sum(1 for w in mots_norm if w.startswith(r))
                else:
                    c = sum(1 for w in mots_norm if w == r)
                if not c:
                    ok = False
                    break
                n += min(c, 3)
            if ok:
                meilleur = max(meilleur, n / len(alt))
        if meilleur:
            dist += 1
            tot += meilleur
    return dist, tot


def entete(a, i=None):
    s = f"[{i}] " if i else ""
    s += f"{a['code']} art. {a['num']} — {CODES[a['code']][1]}"
    return s


def pied_article(a):
    s = f"En vigueur depuis {a['debut']}"
    if a["fin"] != FIN_OUVERTE:
        s += f" jusqu'au {a['fin']} (abrogation programmee)"
    s += f" · https://www.legifrance.gouv.fr/codes/article_lc/{a['legi']}"
    if a["avenir"]:
        s += f"\nUne nouvelle version entre en vigueur le {a['avenir']} : verifier sur Legifrance."
    return s


def chemin_court(a):
    return " > ".join(a["chemin"].split(" > ")[-3:])


def mots_requete(requete):
    dm = _dm()
    q = RE_NUM_ART.sub(" ", requete or "")
    q = RE_NUM_NU.sub(" ", q)
    q = re.sub(r"(?i)\b(articles?|art|code|du|de|des)\b\.?", " ", q)
    for alias in sorted(ALIAS, key=len, reverse=True):
        if len(alias) > 3:
            q = re.sub(r"(?i)(?<![a-z])" + re.escape(alias) + r"(?![a-z])", " ", q)
    return dm.jetons(q)


def chercher(requete, code=None, limite=3):
    dm = _dm()
    con = ouvrir()
    limite = dm.entier(limite, 3, 1, 4)
    code_c = code_de(code) if code else None
    if code and not code_c and str(code).strip().upper() in CODES:
        code_c = str(code).strip().upper()
    code_q = code_c or code_de(requete)
    sorties, deja = [], set()

    # 1) article cite par son numero
    for numn in numeros_cites(requete):
        sql = "SELECT * FROM arts WHERE numn=?"
        p = [numn]
        if code_q:
            sql += " AND code=?"
            p.append(code_q)
        for a in con.execute(sql + " ORDER BY code", p).fetchall():
            if a["id"] in deja or len(sorties) >= limite:
                continue
            deja.add(a["id"])
            autres_mots = mots_requete(requete)
            if len(a["texte"]) <= 1200:
                ext = a["texte"]
            elif autres_mots:
                ext = dm.extrait(a["texte"], [dm.racine(m) for m in autres_mots], 1200)
            else:
                ext = a["texte"][:1200].rsplit(" ", 1)[0] + " […]"
            sorties.append(f"{entete(a, len(sorties) + 1)}\n{chemin_court(a)}\n{pied_article(a)}\n{ext}"
                           + (f"\n(suite : lire_article(\"{a['code']}\", \"{a['num']}\"))"
                              if len(a["texte"]) > 1200 else ""))
        if sorties:
            break

    # 2) recherche par mots-cles
    if len(sorties) < limite and not (sorties and numeros_cites(requete)):
        mots = mots_requete(requete)
        if mots:
            groupes = groupes_de(mots)
            racines = [dm.racine(m) for m in mots]
            sql = ("SELECT a.id FROM afts f JOIN arts a ON a.id=f.rowid WHERE afts MATCH ?"
                   + (" AND a.code=?" if code_q else "") + " ORDER BY bm25(afts, 3.0, 1.0) LIMIT 150")
            p = [requete_groupes(groupes, "ou")] + ([code_q] if code_q else [])
            cand = [i for (i,) in con.execute(sql, p).fetchall()]
            notes = []
            for rang, i in enumerate(cand[:80]):
                a = con.execute("SELECT * FROM arts WHERE id=?", (i,)).fetchone()
                mt = dm.mots_normalises(a["texte"])
                dist, tot = couverture_groupes(groupes, mt)
                dist_tout, _ = couverture_groupes(groupes, mt + dm.mots_normalises(a["titre"]))
                taille = min(len(a["texte"]), 8000) / 8000.0
                notes.append((POIDS["dist"] * dist_tout + POIDS["tf"] * tot + POIDS["rang"] / (rang + 4)
                              - POIDS["taille"] * taille, a))
            notes.sort(key=lambda x: -x[0])
            extraits = []
            for _, a in notes:
                if a["id"] in deja or len(sorties) >= limite:
                    continue
                deja.add(a["id"])
                ext = dm.extrait(a["texte"], racines, MAX_EXTRAIT if limite <= 3 else 480)
                extraits.append(ext)
                sorties.append(f"{entete(a, len(sorties) + 1)}\n{chemin_court(a)}\n{pied_article(a)}\n{ext}"
                               + (f"\n(suite : lire_article(\"{a['code']}\", \"{a['num']}\"))"
                                  if len(a["texte"]) > len(ext) else ""))
            alerte = dm.verifier_chiffres(requete, extraits) if extraits else ""
    maj = meta(con, "lois_construit_le")[:10]
    con.close()
    if "alerte" not in locals():
        alerte = ""
    if not sorties:
        return ("Aucun article trouve. Essaie d'autres mots-cles, ou cite le numero "
                "(ex. « article 279 CGI », « L225-1 code de commerce »).")
    return ("\n\n".join(sorties) + alerte
            + f"\n---\nCodes consolides Legifrance (base du {maj}). Cite uniquement ces articles, avec leur code et "
              "leur numero ; verifie que le texte confirme ce que dit l'utilisateur.")


def doctrine_associee(dm, code, num, maxi=4):
    """Documents BOFiP qui citent le plus l'article (CGI) : pour que le modele les ouvre
    au lieu de s'en tenir au seul texte de loi. Renvoie '' en cas de doute ou d'erreur."""
    if code != "CGI" or not num:
        return ""
    try:
        n = re.escape(num)
        rx = re.compile(r"(?:articles?\s+%s(?![-\w])(?!\s[A-Z]\b)|(?<![\w-])%s\s+du\s+CGI)" % (n, n),
                        re.IGNORECASE)
        q = '"article %s" OR "articles %s" OR "%s du cgi"' % (num, num, num)
        con = dm.ouvrir()
        cnt, titres = {}, {}
        for r in con.execute(
                "SELECT c.doc AS doc, c.texte AS texte, d.titre AS titre FROM fts "
                "JOIN chunks c ON c.id = fts.rowid JOIN docs d ON d.id = c.doc "
                "WHERE fts MATCH ? AND d.type <> 'Actualit\u00e9' LIMIT 6000", (q,)):
            k = len(rx.findall(r["texte"]))
            if k:
                cnt[r["doc"]] = cnt.get(r["doc"], 0) + k
                titres[r["doc"]] = r["titre"] or ""
        con.close()
    except Exception:  # noqa: BLE001
        return ""
    if not cnt:
        return ""
    best = sorted(cnt.items(), key=lambda x: (-x[1], x[0]))[:maxi]
    morceaux = []
    for doc, _ in best:
        fin = re.split(r"\s+[-\u2013]\s+", titres[doc])[-1].strip()
        morceaux.append(f'lire_document("{doc}") [{fin[:90]}]')
    return ("\n[BOFiP citant le plus cet article : ouvre celui qui correspond a la question "
            "(beneficiaires et champ d'application, conditions, exclusions) avant de repondre : "
            + " ; ".join(morceaux) + "]")


def lire(code, numero, page=1):
    dm = _dm()
    con = ouvrir()
    page = dm.entier(page, 1, 1, 1000)
    code_c = code_de(code) if code else None
    if code and not code_c and str(code).strip().upper() in CODES:
        code_c = str(code).strip().upper()
    numn = norm_num(numero)
    if not numn:
        con.close()
        return "Donne le numero de l'article (ex. 279, L225-1, 278-0 bis)."
    sql = "SELECT * FROM arts WHERE numn=?"
    p = [numn]
    if code_c:
        sql += " AND code=?"
        p.append(code_c)
    rows = con.execute(sql + " ORDER BY code", p).fetchall()
    con.close()
    if not rows:
        return (f"Article {numero} introuvable" + (f" dans {CODES[code_c][1]}" if code_c else "")
                + ". Codes disponibles : " + ", ".join(f"{k} ({v[1]})" for k, v in CODES.items()) + ".")
    if len(rows) > 1:
        return ("Plusieurs codes ont un article " + numero + " : "
                + "; ".join(f"{r['code']} ({CODES[r['code']][1]})" for r in rows)
                + ". Precise le code.")
    a = rows[0]
    t = a["texte"]
    pages, cur = [], ""
    for ligne in t.split("\n"):
        if cur and len(cur) + len(ligne) + 1 > MAX_PAGE:
            pages.append(cur)
            cur = ""
        while len(ligne) > MAX_PAGE:
            pages.append(ligne[:MAX_PAGE])
            ligne = ligne[MAX_PAGE:]
        cur = (cur + "\n" + ligne) if cur else ligne
    pages.append(cur)
    if page > len(pages):
        return f"{a['code']} art. {a['num']} : {len(pages)} page(s) seulement."
    suite = (f"\n[Suite : lire_article(\"{a['code']}\", \"{a['num']}\", page={page + 1})]"
             if page < len(pages) else doctrine_associee(dm, a["code"], a["num"]))
    return (f"{entete(a)}\n{chemin_court(a)}\n{pied_article(a)}\n"
            f"(page {page}/{len(pages)})\n\n{pages[page - 1]}{suite}")


def info():
    con = ouvrir()
    s = (f"Codes : {meta(con, 'lois_articles')} articles en vigueur ({meta(con, 'lois_detail')})\n"
         f"Construit le : {meta(con, 'lois_construit_le')}")
    con.close()
    return s
