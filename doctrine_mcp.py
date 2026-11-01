#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Serveur MCP local : recherche dans la doctrine fiscale officielle (BOFiP-Impots en vigueur)
et, a terme, dans la reglementation comptable. Aucune dependance externe : Python 3.9+ seulement.

Commandes :
  python doctrine_mcp.py construire            telecharge le BOFiP et construit l'index (a refaire chaque semaine)
  python doctrine_mcp.py serveur               serveur MCP (stdio) : c'est ce que lance Hermes (ou tout client MCP)
  python doctrine_mcp.py chercher "texte" [serie]   test en ligne de commande
  python doctrine_mcp.py lire BOI-TVA-LIQ-30-20-10-20 [passage]
  python doctrine_mcp.py info

Source des donnees : jeu de donnees « BOFiP-Impots - publications en vigueur » (DGFiP),
data.economie.gouv.fr, Licence Ouverte v2.0 (Etalab).
"""
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.request
from html.parser import HTMLParser

VERSION = "0.9"
ICI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ICI, "doctrine.sqlite")
DOSSIER_DONNEES = os.path.join(ICI, "donnees")

URL_BOFIP = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/bofip-vigueur/exports/jsonl"
    "?select=identifiant_juridique%2Ctype%2Ctitre%2Cserie%2Cdivision%2Cdebut_de_validite%2Cpermalien%2Ccontenu_html"
    "&timezone=Europe%2FParis"
)

TAILLE_PASSAGE = 1500  # caracteres visés par passage indexé
MAX_BLOC = 1800        # un bloc plus long est coupé


# --------------------------------------------------------------------------- utilitaires

def log(*a):
    print(*a, file=sys.stderr, flush=True)


def norm(s):
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


# --------------------------------------------------------------------------- HTML -> blocs

class Extracteur(HTMLParser):
    """Transforme le HTML du BOFiP en blocs de texte, en gardant le numero de paragraphe courant."""

    BLOCS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "div", "blockquote",
             "ul", "ol", "table", "caption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocs = []      # (numero_paragraphe, texte)
        self.cur = []
        self.par = None
        self.in_num = False

    def _flush(self):
        texte = norm("".join(self.cur))
        self.cur = []
        if texte:
            self.blocs.append((self.par, texte))

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCS:
            self._flush()
        if tag == "p":
            cls = dict(attrs).get("class") or ""
            if "numero-de-paragraphe" in cls:
                self.in_num = True
        elif tag in ("td", "th"):
            self.cur.append(" | ")
        elif tag == "br":
            self.cur.append(" ")

    def handle_endtag(self, tag):
        if tag == "p" and self.in_num:
            num = norm("".join(self.cur))
            self.cur = []
            self.in_num = False
            if num:
                self.par = num
            return
        if tag in self.BLOCS:
            self._flush()

    def handle_data(self, data):
        self.cur.append(data)


def html_vers_blocs(contenu_html):
    # Les attributs du jeu de donnees ont des guillemets doubles doubles ("") : on les normalise.
    h = (contenu_html or "").replace('""', '"')
    ex = Extracteur()
    try:
        ex.feed(h)
        ex.close()
    except Exception:
        pass
    ex._flush()
    return ex.blocs


def decouper_long(texte, maxi=MAX_BLOC):
    if len(texte) <= maxi:
        return [texte]
    morceaux, reste = [], texte
    while len(reste) > maxi:
        coupe = max(reste.rfind(". ", 0, maxi), reste.rfind("; ", 0, maxi), reste.rfind(" | ", 0, maxi))
        if coupe < maxi // 2:
            coupe = reste.rfind(" ", 0, maxi)
        if coupe <= 0:
            coupe = maxi
        morceaux.append(reste[:coupe + 1].strip())
        reste = reste[coupe + 1:].strip()
    if reste:
        morceaux.append(reste)
    return morceaux


def blocs_vers_passages(blocs):
    """Regroupe les blocs en passages d'environ TAILLE_PASSAGE caracteres.
    Retourne une liste de (libelle_paragraphes, texte)."""
    passages = []
    cur, cur_len, pars = [], 0, []
    dernier_par = object()

    def clore():
        nonlocal cur, cur_len, pars
        if cur:
            if pars:
                lib = pars[0] if pars[0] == pars[-1] else f"{pars[0]}-{pars[-1]}"
            else:
                lib = ""
            passages.append((lib, "\n".join(cur)))
        cur, cur_len, pars = [], 0, []

    for par, texte in blocs:
        for morceau in decouper_long(texte):
            if cur and cur_len + len(morceau) > TAILLE_PASSAGE:
                clore()
                dernier_par = object()  # on repete le numero au debut du passage suivant
            prefixe = ""
            if par is not None and par != dernier_par:
                prefixe = f"[§ {par}] "
                dernier_par = par
            if par is not None and (not pars or pars[-1] != par):
                pars.append(par)
            cur.append(prefixe + morceau)
            cur_len += len(morceau) + len(prefixe) + 1
    clore()
    return passages


# --------------------------------------------------------------------------- construction de l'index

SCHEMA = """
CREATE TABLE docs(
  id TEXT PRIMARY KEY, source TEXT, type TEXT, serie TEXT, division TEXT,
  titre TEXT, debut TEXT, url TEXT, nb INTEGER);
CREATE TABLE chunks(
  id INTEGER PRIMARY KEY, doc TEXT, n INTEGER, par TEXT, titre TEXT, texte TEXT);
CREATE INDEX chunks_doc ON chunks(doc, n);
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
CREATE VIRTUAL TABLE fts USING fts5(
  titre, texte, content='chunks', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2');
"""


def telecharger(url, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    tmp = destination + ".part"
    for essai in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "doctrine-mcp/" + VERSION})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                total, debut, dernier = 0, time.time(), 0
                while True:
                    bloc = r.read(1 << 20)
                    if not bloc:
                        break
                    f.write(bloc)
                    total += len(bloc)
                    if time.time() - dernier > 2:
                        dernier = time.time()
                        log(f"  telecharge : {total / 1e6:.0f} Mo ({total / 1e6 / max(1, time.time() - debut):.1f} Mo/s)")
            os.replace(tmp, destination)
            log(f"  telechargement termine : {total / 1e6:.0f} Mo")
            return
        except Exception as e:  # noqa: BLE001
            log(f"  echec du telechargement (essai {essai}/3) : {e}")
            time.sleep(3 * essai)
    raise SystemExit("Telechargement impossible. Verifie la connexion internet puis relance.")


def construire(args):
    fichier = None
    if "--fichier" in args:
        fichier = args[args.index("--fichier") + 1]
    if fichier is None:
        fichier = os.path.join(DOSSIER_DONNEES, "bofip.jsonl")
        log("1/3 Telechargement du BOFiP en vigueur (data.economie.gouv.fr)...")
        telecharger(URL_BOFIP, fichier)
    else:
        log(f"1/3 Utilisation du fichier local {fichier}")

    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        c.close()
    except sqlite3.OperationalError:
        raise SystemExit("Cette version de Python/SQLite n'a pas FTS5. Installe Python depuis python.org ou scoop.")

    log("2/3 Analyse et indexation...")
    tmp = DB + ".tmp"
    for p in (tmp, tmp + "-journal"):
        if os.path.exists(p):
            os.remove(p)
    con = sqlite3.connect(tmp)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")
    con.executescript(SCHEMA)

    deja, nb_docs, nb_pass = set(), 0, 0
    debut = time.time()
    with open(fichier, "r", encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                d = json.loads(ligne)
            except ValueError:
                continue
            ident = (d.get("identifiant_juridique") or "").strip()
            if not ident:
                continue
            if ident in deja:
                k = 2
                while f"{ident}#{k}" in deja:
                    k += 1
                ident = f"{ident}#{k}"
            deja.add(ident)
            titre = norm(d.get("titre") or "")
            passages = blocs_vers_passages(html_vers_blocs(d.get("contenu_html")))
            if not passages:
                continue
            con.execute(
                "INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?)",
                (ident, "bofip", d.get("type"), d.get("serie"), d.get("division"), titre,
                 d.get("debut_de_validite"), d.get("permalien"), len(passages)))
            con.executemany(
                "INSERT INTO chunks(doc, n, par, titre, texte) VALUES (?,?,?,?,?)",
                [(ident, i + 1, lib, titre, txt) for i, (lib, txt) in enumerate(passages)])
            nb_docs += 1
            nb_pass += len(passages)
            if nb_docs % 500 == 0:
                log(f"  {nb_docs} documents, {nb_pass} passages ({time.time() - debut:.0f} s)")
    log(f"  {nb_docs} documents, {nb_pass} passages. Construction de l'index de recherche...")
    con.execute("INSERT INTO fts(fts) VALUES('rebuild')")
    con.execute("INSERT INTO meta VALUES ('construit_le', ?)", (time.strftime("%Y-%m-%d %H:%M"),))
    con.execute("INSERT INTO meta VALUES ('bofip_documents', ?)", (str(nb_docs),))
    con.execute("INSERT INTO meta VALUES ('bofip_passages', ?)", (str(nb_pass),))
    con.commit()
    con.close()
    os.replace(tmp, DB)
    log(f"3/3 Termine : {DB} ({os.path.getsize(DB) / 1e6:.0f} Mo)")


# --------------------------------------------------------------------------- recherche

MOTS_VIDES = set(
    "le la les l de du des d un une et ou en à a au aux pour par sur dans qui que qu quoi est sont "
    "ce cette ces se son sa ses leur leurs il elle ils elles ne pas plus ni avec sans sous entre "
    "comme mais donc or car si y on nous vous quel quelle quels quelles dont où s n c j m t "
    "encore alors aussi etre être fait faire peut doit pourquoi comment quand quelle quel "
    "applique appliquent s'applique".split())

MAX_EXTRAIT = 650      # caracteres par extrait renvoye
MAX_LECTURE = 3200     # caracteres maximum renvoyes par lire_document


def ouvrir():
    if not os.path.exists(DB):
        raise RuntimeError("L'index n'existe pas encore : lancer « construire.bat » "
                           "dans le dossier du serveur.")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def entier(v, defaut, mini, maxi):
    """Bionic/les petits modeles envoient parfois les nombres sous forme de texte."""
    try:
        n = int(float(str(v).strip()))
    except (TypeError, ValueError):
        n = defaut
    return max(mini, min(n, maxi))


# Sigles de deux ou trois lettres : sans developpement, « taux IS PME » devenait « taux » + « pme » (le « IS » etait ignore).
ACRONYMES = (
    (re.compile(r"\bIS\b", re.I), "impot societes"),
    (re.compile(r"\bIR\b", re.I), "impot revenu"),
    (re.compile(r"\bPME\b", re.I), "petites moyennes entreprises"),
    (re.compile(r"\bPV\b"), "plus values"),
    (re.compile(r"\bCA\b"), "chiffre affaires"),
)


def developper_sigles(q):
    for motif, texte in ACRONYMES:
        q = motif.sub(texte, q or "")
    return q


def jetons(q):
    """Mots-cles de la requete : sans mots vides, sans signes isoles (« 7 », « % »)."""
    bruts = re.findall(r"[^\W_]+", developper_sigles(q).lower())
    mots = [m for m in bruts if m not in MOTS_VIDES and (len(m) >= 3 or (len(m) == 2 and m.isdigit()))]
    if not mots:  # requete du type « 7 » : on la garde telle quelle
        mots = [m for m in bruts if m not in MOTS_VIDES]
    vus, res = set(), []
    for m in mots:
        if m not in vus:
            vus.add(m)
            res.append(m)
    return res[:10]


def racine(m):
    """Racine de recherche par prefixe (restauration -> restau, ce qui couvre aussi « restaurant »)."""
    m = sans_accents(m)
    if m.isdigit() or len(m) <= 3:
        return m
    return m[:6] if len(m) >= 8 else m[:max(4, len(m) - 2)] if len(m) >= 6 else m


def requete_fts(mots, mode):
    termes = []
    for m in mots:
        r = racine(m)
        # Le tokenizer FTS5 ignore les accents ; on cherche donc sur la forme sans accent.
        if len(r) >= 4 and not r.isdigit():
            termes.append(f'"{r}"*')
        else:
            termes.append(f'"{r}"')
    return (" OR " if mode == "ou" else " ").join(termes)


def mots_normalises(texte):
    return re.findall(r"[^\W_]+", sans_accents(texte.lower()))


def couverture(racines, mots):
    """(nombre de mots-cles distincts presents, total d'occurrences plafonnees)."""
    distincts, total = 0, 0.0
    for r in racines:
        if len(r) >= 4 and not r.isdigit():
            n = sum(1 for w in mots if w.startswith(r))
        else:
            n = sum(1 for w in mots if w == r)
        if n:
            distincts += 1
            total += min(n, 3)
    return distincts, total


def meta(con, cle, defaut=""):
    r = con.execute("SELECT v FROM meta WHERE k=?", (cle,)).fetchone()
    return r[0] if r else defaut


def extrait(texte, racines, maxi=MAX_EXTRAIT):
    """Garde les lignes les plus pertinentes du passage, en gardant leur numero de paragraphe."""
    lignes, cur_par, items = texte.split("\n"), None, []
    for i, l in enumerate(lignes):
        m = re.match(r"\[§ ([^\]]+)\]", l)
        if m:
            cur_par = m.group(1)
        d, t = couverture(racines, mots_normalises(l))
        items.append((i, cur_par, l, d * 3 + t))
    if sum(len(l) for l in lignes) <= maxi:
        return texte
    classes = sorted(items, key=lambda x: (-x[3], x[0]))
    if not classes or classes[0][3] <= 0:  # aucun mot-cle dans le passage : on garde le debut
        coupe = texte[:maxi]
        return coupe if len(texte) <= maxi else coupe.rsplit(" ", 1)[0] + " […]"
    choisis, taille = [], 0
    for i, par, l, sc in classes:
        if choisis and (sc <= 0 or taille + len(l) > maxi):
            continue
        if len(l) > maxi:
            l = l[:maxi].rsplit(" ", 1)[0] + " […]"
        choisis.append((i, par, l))
        taille += len(l)
        if taille >= maxi:
            break
    choisis.sort()
    morceaux, prec = [], -1
    for i, par, l in choisis:
        if not l.startswith("[§") and par:
            l = f"[§ {par}] {l}"
        if prec != -1 and i > prec + 1:
            morceaux.append("[…]")
        morceaux.append(l)
        prec = i
    return "\n".join(morceaux)


def candidats_fts(con, mots, serie, source, actu, maxi_docs, minimum):
    """Documents candidats d'apres FTS5 (ET puis OU). actu=True : seulement les actualites."""
    sql = """
      SELECT c.doc
      FROM fts JOIN chunks c ON c.id = fts.rowid JOIN docs d ON d.id = c.doc
      WHERE fts MATCH ? AND d.type %s 'Actualité'""" % ("=" if actu else "<>")
    if serie:
        sql += " AND upper(d.serie) = upper(?)"
    if source:
        sql += " AND d.source = ?"
    sql += " ORDER BY bm25(fts, 4.0, 1.0) LIMIT 250"
    trouves = []
    for mode in ("et", "ou"):
        p = [requete_fts(mots, mode)]
        if serie:
            p.append(serie)
        if source:
            p.append(source)
        for ligne in con.execute(sql, p).fetchall():
            if ligne["doc"] not in trouves:
                trouves.append(ligne["doc"])
        if len(trouves) >= minimum:
            break
    return trouves[:maxi_docs]


def noter_documents(con, docs, racines, series_pref=()):
    res = []
    for rang, doc in enumerate(docs):
        d = con.execute("SELECT * FROM docs WHERE id=?", (doc,)).fetchone()
        titre_cov, _ = couverture(racines, mots_normalises(d["titre"]))
        notes = []
        for c in con.execute("SELECT n, par, texte FROM chunks WHERE doc=? ORDER BY n", (doc,)):
            dist, tot = couverture(racines, mots_normalises(c["texte"]))
            notes.append((dist * 10 + tot * 0.6, c["n"], c["par"], c["texte"]))
        notes.sort(key=lambda x: (-x[0], x[1]))
        meilleur = notes[0]
        score = meilleur[0] + titre_cov * 6 - rang * 0.15
        if series_pref and (d["serie"] or "").upper() in series_pref:
            score += 15     # la question cite le sigle de la serie (IS, TVA, BIC...)
        autres = [n[1] for n in notes[1:4] if n[0] >= max(10, meilleur[0] * 0.6)]
        res.append((score, d, meilleur, autres))
    res.sort(key=lambda x: -x[0])
    return res


def pourcentages(texte):
    """Pourcentages cites dans un texte, normalises (« 5,50 % » -> « 5,5 % »)."""
    res = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:%|pour ?cent)", texte or ""):
        n = m.group(1).replace(".", ",")
        if "," in n:
            n = n.rstrip("0").rstrip(",")
        res.append(n + " %")
    return res


def verifier_chiffres(requete, extraits):
    """Si la question cite un taux qu'aucun extrait ne contient, previent le modele."""
    demandes = list(dict.fromkeys(pourcentages(requete)))
    if not demandes:
        return ""
    trouves = list(dict.fromkeys(p for e in extraits for p in pourcentages(e)))
    absents = [d for d in demandes if d not in trouves]
    if not absents:
        return ""
    liste = ", ".join(trouves[:6]) if trouves else "aucun taux"
    return ("\nATTENTION : " + ", ".join(absents) + " de la question n'apparait dans aucun passage ci-dessus "
            f"(taux trouves : {liste}). Ne reprends pas ce chiffre comme exact : dis a l'utilisateur "
            "que les passages ne le confirment pas et cite ceux qui s'appliquent.")



SERIES_SIGLES = {"IS", "IR", "TVA", "BIC", "BNC", "BA", "ENR", "RPPM", "RSA", "CF", "IF", "PAT", "CVAE", "TCA", "RFPI"}


def chercher(requete, serie=None, limite=3, source=None):
    con = ouvrir()
    limite = entier(limite, 3, 1, 4)
    serie = (str(serie).strip() or None) if serie else None
    mots = jetons(requete)
    if not mots:
        return "Requete vide : donne quelques mots-cles (ex. « taux TVA restauration sur place »)."
    racines = [racine(m) for m in mots]
    # Sigles de serie cites dans la question (« taux IS PME », « TVA ... ») : bonus aux documents de cette serie.
    prefs = {m.upper() for m in re.findall(r"[^\W_]+", requete or "") if m.upper() in SERIES_SIGLES}
    # Une annee (« 2026 ») ne doit pas exclure les documents qui ne la citent pas : elle sert au classement seulement.
    mots_fts = [m for m in mots if not re.fullmatch(r"(?:19|20)\d\d", m)]
    if len(mots_fts) < 2:
        mots_fts = mots
    # Les documents « Contenu » (BOI-...) d'abord ; les actualites (ACTU-...) seulement en complement.
    principaux = noter_documents(
        con, candidats_fts(con, mots_fts, serie, source, False, 30, max(limite * 3, 10)), racines, prefs)
    resultats = principaux[:limite]
    if len(resultats) < limite:
        actus = noter_documents(
            con, candidats_fts(con, mots_fts, serie, source, True, 10, 6), racines, prefs)
        resultats += actus[:limite - len(resultats)]
    if not resultats:
        con.close()
        return ("Aucun resultat. Essaie d'autres mots-cles, ou un numero d'article "
                "(ex. « 279 », « 278-0 bis »).")

    sorties, extraits = [], []
    for i, (score, d, (sc, n, par, texte), autres) in enumerate(resultats, 1):
        en_tete = f"[{i}] {d['id']}"
        if par:
            en_tete += f" — § {par}"
        en_tete += f" (passage {n}/{d['nb']})"
        if (d["type"] or "").lower().startswith("actu"):
            en_tete += " [actualite BOFiP, peut etre depassee]"
        ext = extrait(texte, racines, MAX_EXTRAIT if limite <= 3 else 480)
        extraits.append(ext)
        bloc = f"{en_tete}\n{d['titre']}\nEn vigueur depuis {d['debut']} · {d['url']}\n{ext}"
        if autres:
            bloc += f"\n(autres passages pertinents : {', '.join(map(str, autres))})"
        sorties.append(bloc)
    pied = (verifier_chiffres(requete, extraits) + f"\n---\nBOFiP en vigueur (base du {meta(con, 'construit_le')[:10]}). "
            "Verifie que ces passages confirment ce que dit l'utilisateur ; sinon, dis-le. "
            "Cite uniquement ces references (identifiant + §) ; « passage N/M » est un numero interne, jamais un §. Si ces passages ne couvrent qu'un cas particulier, "
            "ne generalise pas : relance une recherche. Le BOFiP ne traite pas la paie ni les cotisations "
            "(-> rechercher_boss). Suite : lire_document(identifiant, passage).")
    con.close()
    return "\n\n".join(sorties) + pied


def lire(identifiant, passage=1, nombre=2):
    if (identifiant or "").strip().upper().startswith("BOSS"):
        import boss
        return boss.lire(identifiant, passage, nombre)
    con = ouvrir()
    ident = (identifiant or "").strip()
    d = con.execute("SELECT * FROM docs WHERE upper(id)=upper(?)", (ident,)).fetchone()
    if not d:
        voisins = con.execute(
            "SELECT id, titre FROM docs WHERE upper(id) LIKE upper(?) ORDER BY id LIMIT 12",
            (ident + "%",)).fetchall()
        con.close()
        if not voisins:
            return f"Aucun document dont l'identifiant commence par « {ident} »."
        return "Identifiants proches :\n" + "\n".join(f"- {v['id']} : {v['titre'][:110]}" for v in voisins)
    passage = entier(passage, 1, 1, 10000)
    nombre = entier(nombre, 2, 1, 3)
    rows = con.execute(
        "SELECT n, par, texte FROM chunks WHERE doc=? AND n>=? AND n<? ORDER BY n",
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
    suite = ""
    if dernier < d["nb"]:
        suite = f"\n\n[Suite : lire_document(\"{d['id']}\", passage={dernier + 1})]"
    return (f"{d['id']} — {d['titre']}\nEn vigueur depuis {d['debut']} · {d['url']}\n\n"
            + "\n\n".join(corps) + suite)


def info():
    try:
        con = ouvrir()
        s = (f"Index : {DB} ({os.path.getsize(DB) / 1e6:.0f} Mo)\n"
             f"Construit le : {meta(con, 'construit_le')}\n"
             f"BOFiP : {meta(con, 'bofip_documents')} documents, {meta(con, 'bofip_passages')} passages")
        con.close()
    except Exception as e:  # noqa: BLE001
        s = f"BOFiP : non disponible ({e})"
    try:
        import legislation
        s += "\n" + legislation.info()
    except Exception as e:  # noqa: BLE001
        s += f"\nCodes : non disponibles ({e})"
    try:
        import boss
        s += "\n" + boss.info()
    except Exception as e:  # noqa: BLE001
        s += f"\nBOSS : non disponible ({e})"
    try:
        import normes
        s += "\n" + normes.info()
    except Exception as e:  # noqa: BLE001
        s += f"\nNormes comptables : non disponibles ({e})"
    return s


# --------------------------------------------------------------------------- serveur MCP (stdio)

OUTILS = [
    {
        "name": "rechercher_doctrine",
        "description": (
            "Recherche dans la doctrine fiscale officielle francaise (BOFiP-Impots en vigueur, ~9 000 documents : "
            "TVA, IS, IR, BIC, BNC, RPPM, ENR, CF, etc.). A UTILISER AVANT de repondre a toute question de fiscalite "
            "(taux, regimes, conditions, articles du CGI cites par l'administration). Retourne des passages avec "
            "l'identifiant du document (BOI-...), le numero de paragraphe (§) et le lien officiel. "
            "Ne cite que les references renvoyees par cet outil ; si rien ne correspond, dis-le. "
            "IMPORTANT : verifie que les passages confirment bien l'affirmation de l'utilisateur (taux, date, condition) ; "
            "s'ils la contredisent, corrige-la en citant le passage."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "OBLIGATOIRE. Mots-cles en francais, de preference des mots complets (« impot sur les societes » plutot que « IS »), ex. « taux TVA restauration sur place »"},
                "serie": {"type": ["string", "null"], "description": "Optionnel (laisser vide si doute) : serie du BOFiP (TVA, IS, BIC, IR, BNC, RPPM, ENR, CF, CVAE, TCA...)"},
                "limite": {"type": ["integer", "string", "null"], "description": "Nombre de documents (1 a 4, defaut 3)"},
            },
        },
    },
    {
        "name": "lire_document",
        "description": (
            "Lit un document du BOFiP (ex. BOI-TVA-LIQ-30-20-10-20) ou du BOSS (ex. BOSS-exonerations-allegements-generaux) par son identifiant exact, passage par passage. "
            "Si l'identifiant est incomplet, renvoie la liste des identifiants proches."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifiant": {"type": "string", "description": "OBLIGATOIRE. Identifiant juridique, ex. BOI-TVA-LIQ-30-20-10-20"},
                "passage": {"type": ["integer", "string", "null"], "description": "Numero du premier passage a lire (defaut 1)"},
                "nombre": {"type": ["integer", "string", "null"], "description": "Nombre de passages (1 a 3, defaut 2)"},
            },
        },
    },
    {
        "name": "rechercher_boss",
        "description": (
            "Recherche dans le BOSS (Bulletin officiel de la securite sociale, boss.gouv.fr) : doctrine administrative "
            "sur les cotisations sociales, assiette, exonerations et allegements (reduction generale), avantages en nature, "
            "frais professionnels, bulletin de paie, protection sociale complementaire, effectif, CSG/CRDS, mesures "
            "exceptionnelles, rescrits, et tables de parametres (plafond de la securite sociale, taux, seuils). "
            "A UTILISER AVANT de repondre a toute question de paie ou de cotisations sociales. Retourne des passages avec "
            "l'identifiant (BOSS-...), le numero de paragraphe (§) et le lien officiel. Ne cite que les references "
            "renvoyees ; verifie qu'elles confirment l'affirmation de l'utilisateur (taux, seuil, date) et corrige-la sinon. "
            "Pour le texte meme de la loi, utilise rechercher_loi (code CSS ou CT)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "OBLIGATOIRE. Mots-cles en francais, ex. « avantage en nature vehicule » ou « reduction generale degressive »"},
                "theme": {"type": ["string", "null"], "description": "Optionnel (laisser vide si doute) : bulletin-de-paie, regles-dassujettissement, exonerations, autres-elements-de-remuneration, mesures-exceptionnelles, rescrits, table-des-parametres"},
                "limite": {"type": ["integer", "string", "null"], "description": "Nombre de passages (1 a 4, defaut 3)"},
            },
        },
    },
    {
        "name": "rechercher_loi",
        "description": (
            "Recherche dans les CODES consolides (Legifrance) : Code de commerce (societes commerciales, comptabilite "
            "des commercants, registre), Code civil (societes civiles art. 1832 s., contrats, regimes), CGI, LPF et "
            "Code monetaire et financier, Code des impositions sur les biens et services (CIBS), Code du travail (CT) et Code de la securite sociale (CSS). A UTILISER pour toute question de droit des societes, de droit du travail, de cotisations sociales ou sur le texte meme d'un "
            "article (le BOFiP, lui, commente les textes fiscaux). Accepte des mots-cles ou un numero d'article "
            "(« article 279 CGI », « L225-1 code de commerce »). Ne cite que les articles renvoyes ; verifie qu'ils "
            "confirment l'affirmation de l'utilisateur. Pour les regles comptables (PCG), utilise rechercher_norme."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "OBLIGATOIRE. Mots-cles ou numero d'article, ex. « SARL cession de parts agrement » ou « article L223-14 code de commerce »"},
                "code": {"type": ["string", "null"], "description": "Optionnel : CGI, LPF, COM (Code de commerce), CIV (Code civil), CMF, CIBS, CT (Code du travail), CSS (Code de la securite sociale)"},
                "limite": {"type": ["integer", "string", "null"], "description": "Nombre d'articles (1 a 4, defaut 3)"},
            },
        },
    },
    {
        "name": "lire_article",
        "description": (
            "Lit le texte integral d'un article de code en vigueur. Exemples : code=COM numero=L223-14 ; "
            "code=CGI numero=278-0 bis ; code=CIV numero=1843-3 ; code=CT numero=L1221-1 ; code=CSS numero=L241-13."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "CGI, LPF, COM (Code de commerce), CIV (Code civil), CMF, CIBS, CT (Code du travail) ou CSS (Code de la securite sociale)"},
                "numero": {"type": "string", "description": "Numero de l'article, ex. 279, L225-1, 278-0 bis"},
                "page": {"type": ["integer", "string", "null"], "description": "Page du texte si l'article est long (defaut 1)"},
            },
        },
    },
    {
        "name": "rechercher_norme",
        "description": (
            "Recherche dans les NORMES COMPTABLES francaises de l'ANC (version 2026) : Plan comptable general "
            "(reglement 2014-03 : comptabilisation, evaluation, amortissements, depreciations, provisions, "
            "stocks, immobilisations, fonds commercial, plan de comptes et fonctionnement des comptes, "
            "comptes annuels), comptes consolides (reglement 2020-01) et associations/fondations (reglement 2018-06). "
            "A UTILISER AVANT de repondre a toute question de comptabilite (traitement comptable, numero ou "
            "fonctionnement d'un compte, duree ou methode d'amortissement, contenu des comptes annuels). "
            "Accepte des mots-cles ou un numero d'article du PCG (« 214-3 »). Pour le texte des lois "
            "(code de commerce) ou la fiscalite, utilise rechercher_loi / rechercher_doctrine. "
            "Ne cite que les articles renvoyes ; verifie qu'ils confirment l'affirmation de l'utilisateur "
            "(duree, taux, compte) et corrige-la sinon."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "OBLIGATOIRE. Mots-cles ou numero d'article, ex. « amortissement fonds commercial » ou « compte 6811 dotations »"},
                "source": {"type": ["string", "null"], "description": "Optionnel (laisser vide si doute) : PCG, RECUEIL (PCG + commentaires), ASSO (associations), CONSO (comptes consolides)"},
                "limite": {"type": ["integer", "string", "null"], "description": "Nombre d'articles (1 a 4, defaut 3)"},
            },
        },
    },
    {
        "name": "lire_norme",
        "description": (
            "Lit le texte d'un article des normes comptables ANC. Exemples : identifiant=214-3 (PCG), "
            "« PCG art. 1121-1 » (plan de comptes), « ASSO art. 112-1 ». Renvoie les passages suivants si l'article est long."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifiant": {"type": "string", "description": "OBLIGATOIRE. Numero d'article, ex. 214-3, ou identifiant renvoye par rechercher_norme (« PCG art. 214-3 »)"},
                "passage": {"type": ["integer", "string", "null"], "description": "Numero du premier passage a lire (defaut 1)"},
                "nombre": {"type": ["integer", "string", "null"], "description": "Nombre de passages (1 a 3, defaut 2)"},
            },
        },
    },
]


MANDATAIRES = {
    "rechercher_doctrine": ("requete",), "rechercher_boss": ("requete",), "rechercher_loi": ("requete",),
    "rechercher_norme": ("requete",), "lire_document": ("identifiant",), "lire_norme": ("identifiant",),
    "lire_article": ("code", "numero"),
}
ALIAS_ARGS = {
    "requete": ("query", "question", "recherche", "q", "mots_cles", "mots-cles", "motscles", "texte", "terms", "search", "keywords"),
    "identifiant": ("id", "identifier", "document", "doc", "reference", "ref"),
    "numero": ("article", "num", "number", "n"),
    "code": ("code_juridique",),
}


def normaliser_args(nom, a):
    """Tolere les arguments mal nommes par le modele (query, question...) et signale clairement ceux qui manquent."""
    a = dict(a or {})
    if isinstance(a.get("params"), dict) and not any(k in a for k in MANDATAIRES.get(nom, ())):
        a = dict(a["params"])
    for cle in MANDATAIRES.get(nom, ()):
        if str(a.get(cle) or "").strip():
            continue
        for alias in ALIAS_ARGS.get(cle, ()):
            if str(a.get(alias) or "").strip():
                a[cle] = a[alias]
                break
    manquants = [c for c in MANDATAIRES.get(nom, ()) if not str(a.get(c) or "").strip()]
    if manquants:
        exemple = {"requete": 'requete="avantage en nature vehicule"', "identifiant": 'identifiant="BOSS-..."',
                   "code": 'code="CGI"', "numero": 'numero="279"'}
        raise ValueError(f"argument obligatoire manquant : {', '.join(manquants)}. Relance {nom} en le renseignant "
                         f"(ex. {exemple.get(manquants[0], manquants[0] + '=...')}).")
    return a


RE_SOCIAL = re.compile(
    r"cotisation|urssaf|\bpaie\b|bulletin|avantages? en nature|\bsmic\b|plafond.{0,20}securite sociale|\bpass\b|"
    r"\bcsg\b|\bcrds\b|charges? sociales?|reduction generale|allegement|frais professionnel|indemnites? kilometrique|"
    r"heures? supplementaire|prevoyance|protection sociale|titres?.restaurant|gratification|assiette.{0,20}sociale|"
    r"net social|\bforfait social\b|rupture conventionnelle|indemnite de licenciement|apprenti|salarie")


RE_TRAVAIL = re.compile(
    r"periode d.essai|preavis|\bcdd\b|\bcdi\b|conges? payes?|demission|convention collective|temps partiel|"
    r"duree du travail|contrat de travail|contrat a duree|licenciement|salaire minimum|jours? feries?")


def est_travail(requete):
    return bool(RE_TRAVAIL.search(sans_accents(requete or "").lower()))


def est_social(requete):
    return bool(RE_SOCIAL.search(sans_accents(requete or "").lower()))


def sans_pied(texte):
    """Retire le pied de page generique, en gardant l'avertissement « ATTENTION » qui le precede."""
    return texte.split("\n---\n", 1)[0].rstrip()


def doctrine_et_boss(a):
    """Question de paie posee au BOFiP : on ajoute les passages du BOSS, source principale du social."""
    requete = a.get("requete", "")
    lim = entier(a.get("limite", 3), 3, 1, 4)
    part = min(2, lim)   # 2 passages BOSS + 1 passage BOFiP : le contexte du modele local est limite
    import boss
    try:
        b = sans_pied(boss.chercher(requete, None, part))
    except Exception as e:  # noqa: BLE001
        b = f"(BOSS indisponible : {e})"
    f = sans_pied(chercher(requete, a.get("serie"), 1, a.get("source")))
    dates = ""
    try:
        c1, c2 = ouvrir(), boss.ouvrir()
        dates = f" (BOSS du {meta(c2, 'boss_construit_le')[:10]}, BOFiP du {meta(c1, 'construit_le')[:10]})"
        c1.close(); c2.close()
    except Exception:  # noqa: BLE001
        pass
    return ("=== BOSS (securite sociale) : source a privilegier pour la paie et les cotisations ===\n" + b +
            "\n\n=== BOFiP (fiscalite : impot sur le revenu, TVA...) ===\n" + f +
            "\n---\nSources" + dates + ". Verifie que ces passages confirment ce que dit l'utilisateur ; sinon, dis-le. "
            "Cite uniquement ces references (identifiant + §) ; « passage N/M » est un numero interne, jamais un §. Si ces passages ne couvrent qu'un cas particulier, "
            "ne generalise pas : relance une recherche. Suite : lire_document(identifiant, passage).")


def appeler_outil(nom, a):
    a = normaliser_args(nom, a)
    if nom == "rechercher_doctrine" and est_social(a.get("requete", "")) and os.path.exists(os.path.join(ICI, "boss.sqlite")):
        return doctrine_et_boss(a)
    if nom == "rechercher_doctrine" and est_travail(a.get("requete", "")) and os.path.exists(os.path.join(ICI, "legislation.sqlite")):
        import legislation   # droit du travail : le BOFiP n'a rien a dire, on renvoie le Code du travail
        return ("=== Code du travail (le BOFiP ne traite pas le droit du travail) ===\n"
                + legislation.chercher(a.get("requete", ""), "CT", a.get("limite", 3)))
    if nom == "rechercher_doctrine":
        return chercher(a.get("requete", ""), a.get("serie"), a.get("limite", 3), a.get("source"))
    if nom == "lire_document":
        return lire(a.get("identifiant", ""), a.get("passage", 1), a.get("nombre", 2))
    if nom == "rechercher_boss":
        import boss
        return boss.chercher(a.get("requete", ""), a.get("theme") or a.get("serie"), a.get("limite", 3))
    if nom == "rechercher_loi":
        import legislation
        return legislation.chercher(a.get("requete", ""), a.get("code"), a.get("limite", 3))
    if nom == "lire_article":
        import legislation
        return legislation.lire(a.get("code", ""), a.get("numero", ""), a.get("page", 1))
    if nom == "rechercher_norme":
        import normes
        return normes.chercher(a.get("requete", ""), a.get("source"), a.get("limite", 3))
    if nom == "lire_norme":
        import normes
        return normes.lire(a.get("identifiant", ""), a.get("passage", 1), a.get("nombre", 2))
    raise ValueError(f"Outil inconnu : {nom}")


def ecrire(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def repondre_erreur(id_, code, message):
    ecrire({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})


def traiter(msg):
    methode, id_, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if methode is None:
        return  # reponse a une requete du serveur : ignoree
    if id_ is None:
        return  # notification (ex. notifications/initialized)
    if methode == "initialize":
        ecrire({"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": params.get("protocolVersion") or "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "doctrine-fiscale", "version": VERSION}}})
    elif methode == "ping":
        ecrire({"jsonrpc": "2.0", "id": id_, "result": {}})
    elif methode == "tools/list":
        ecrire({"jsonrpc": "2.0", "id": id_, "result": {"tools": OUTILS}})
    elif methode == "tools/call":
        try:
            texte = appeler_outil(params.get("name"), params.get("arguments") or {})
            ecrire({"jsonrpc": "2.0", "id": id_, "result": {
                "content": [{"type": "text", "text": texte}], "isError": False}})
        except Exception as e:  # noqa: BLE001
            ecrire({"jsonrpc": "2.0", "id": id_, "result": {
                "content": [{"type": "text", "text": f"Erreur : {e}"}], "isError": True}})
    elif methode in ("resources/list", "prompts/list"):
        cle = "resources" if methode == "resources/list" else "prompts"
        ecrire({"jsonrpc": "2.0", "id": id_, "result": {cle: []}})
    else:
        repondre_erreur(id_, -32601, f"Methode inconnue : {methode}")


def serveur():
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except Exception:  # noqa: BLE001
        pass
    for ligne in sys.stdin:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            msg = json.loads(ligne)
        except ValueError:
            continue
        try:
            traiter(msg)
        except Exception as e:  # noqa: BLE001
            log("erreur interne :", e)


# --------------------------------------------------------------------------- point d'entree

def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "serveur"
    if cmd == "construire":
        construire(args[1:])
    elif cmd == "construire-lois":
        import legislation
        legislation.construire(args[1:])
    elif cmd == "loi":
        import legislation
        sys.stdout.reconfigure(encoding="utf-8")
        print(legislation.chercher(args[1], args[2] if len(args) > 2 else None))
    elif cmd == "article":
        import legislation
        sys.stdout.reconfigure(encoding="utf-8")
        print(legislation.lire(args[1], args[2], args[3] if len(args) > 3 else 1))
    elif cmd in ("telecharger-boss", "construire-boss", "mise-a-jour-boss", "boss"):
        import boss
        sys.stdout.reconfigure(encoding="utf-8")
        if cmd == "telecharger-boss":
            boss.telecharger(args[1:])
        elif cmd == "construire-boss":
            boss.construire(args[1:])
        elif cmd == "mise-a-jour-boss":
            boss.mise_a_jour(args[1:])
        else:
            print(boss.chercher(args[1], args[2] if len(args) > 2 else None))
    elif cmd == "norme":
        import normes
        sys.stdout.reconfigure(encoding="utf-8")
        print(normes.chercher(args[1], args[2] if len(args) > 2 else None))
    elif cmd == "lire-norme":
        import normes
        sys.stdout.reconfigure(encoding="utf-8")
        print(normes.lire(args[1], args[2] if len(args) > 2 else 1))
    elif cmd == "serveur":
        serveur()
    elif cmd == "chercher":
        sys.stdout.reconfigure(encoding="utf-8")
        print(chercher(args[1], args[2] if len(args) > 2 else None))
    elif cmd == "lire":
        sys.stdout.reconfigure(encoding="utf-8")
        print(lire(args[1], args[2] if len(args) > 2 else 1))
    elif cmd == "info":
        sys.stdout.reconfigure(encoding="utf-8")
        print(info())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
