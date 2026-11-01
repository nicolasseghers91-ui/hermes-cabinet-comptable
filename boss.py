# -*- coding: utf-8 -*-
"""
BOSS - Bulletin officiel de la securite sociale (boss.gouv.fr).

Pas de jeu de donnees ouvert : on telecharge poliment les pages de doctrine du site (une trentaine de fiches
et les tableaux de parametres), puis on les indexe dans boss.sqlite (meme principe que le BOFiP : passages
numerotes avec leur numero de paragraphe).

  python doctrine_mcp.py telecharger-boss     # pages HTML -> donnees/boss/
  python doctrine_mcp.py construire-boss      # donnees/boss/ -> boss.sqlite
  python doctrine_mcp.py mise-a-jour-boss     # les deux

Contenus reutilisables sous licence ODbL (mentions legales de boss.gouv.fr).
"""
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

import doctrine_mcp as dm

BASE = "https://boss.gouv.fr"
RACINE = "/portail/accueil/"
THEMES = ["bulletin-de-paie", "regles-dassujettissement", "exonerations", "autres-elements-de-remuneration",
          "controle", "mesures-exceptionnelles", "rescrits", "table-des-parametres"]
LIBELLES = {
    "bulletin-de-paie": "Bulletin de paie", "regles-dassujettissement": "Regles d'assujettissement",
    "exonerations": "Exonerations", "autres-elements-de-remuneration": "Autres elements de remuneration",
    "controle": "Controle", "mesures-exceptionnelles": "Mesures exceptionnelles", "rescrits": "Rescrits",
    "table-des-parametres": "Table des parametres",
}
DB = os.path.join(dm.ICI, "boss.sqlite")
DOSSIER = os.path.join(dm.DOSSIER_DONNEES, "boss")
PAUSE = 0.6            # secondes entre deux requetes
TAILLE_CHUNK = 1300
MAX_CHUNK = 1700
MAX_EXTRAIT = 650
MAX_LECTURE = 3200

RE_HREF = re.compile(r'href="([^"#?]+)')
_AUTRES = "|".join(t for t in THEMES if t != "rescrits")
RE_PAGE = re.compile(r"^/portail/accueil/(?:(?:" + _AUTRES + r")(?:/[a-z0-9\-]+)?|rescrits(?:/[a-z0-9\-]+){0,2})\.html$")


# --------------------------------------------------------------------------- telechargement

UA_NAV = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/130.0.0.0 Safari/537.36")
EN_TETES = {
    "User-Agent": UA_NAV,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    "Referer": BASE + "/portail/accueil.html",
}
METHODES = ["urllib", "curl", "powershell"]
_methode = {"ok": None}


def _via_urllib(url):
    req = urllib.request.Request(url, headers=EN_TETES)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return 200, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def _via_curl(url):
    sortie = subprocess.run(
        ["curl.exe" if os.name == "nt" else "curl", "-sS", "-L", "--compressed", "--max-time", "60",
         "-A", UA_NAV, "-H", "Accept-Language: fr-FR,fr;q=0.9", "-H", "Accept: text/html,*/*;q=0.8",
         "-e", EN_TETES["Referer"], "-w", "\n__HTTP__%{http_code}", url],
        capture_output=True, timeout=90)
    if sortie.returncode != 0:
        raise RuntimeError("curl : " + sortie.stderr.decode("utf-8", "replace").strip()[:200])
    corps, _, code = sortie.stdout.rpartition(b"\n__HTTP__")
    return int(code or 0), corps


def _via_powershell(url):
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        ok = "try { Invoke-WebRequest -UseBasicParsing -UserAgent '" + UA_NAV + "' " \
             "-Headers @{'Accept-Language'='fr-FR,fr;q=0.9'} -Uri '" + url + "' -OutFile '" + tmp + "'; exit 0 } "
        ko = ("catch { if ($_.Exception.Response) { exit [int]$_.Exception.Response.StatusCode } "
              "else { Write-Error $_; exit 1 } }")
        cmd = "$ProgressPreference='SilentlyContinue'; " + ok + ko
        sortie = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=120)
        if sortie.returncode == 0:
            with open(tmp, "rb") as f:
                return 200, f.read()
        if sortie.returncode in (403, 404, 410, 429, 500, 503):
            return sortie.returncode, b""
        raise RuntimeError("powershell : " + (sortie.stderr or sortie.stdout).decode("utf-8", "replace").strip()[:200])
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


_FONCTIONS = {"urllib": _via_urllib, "curl": _via_curl, "powershell": _via_powershell}


def obtenir(url, essais=2):
    """Texte de la page, None si 404. Essaie urllib, puis curl, puis PowerShell (le site de la Securite sociale
    coupe parfois les connexions de Python seul) ; la methode qui marche est reutilisee."""
    ordre = ([_methode["ok"]] if _methode["ok"] else []) + [m for m in METHODES if m != _methode["ok"]]
    erreurs = []
    for tour in range(essais):
        for m in ordre:
            try:
                code, corps = _FONCTIONS[m](url)
            except Exception as e:  # noqa: BLE001
                erreurs.append(f"{m}: {e}")
                continue
            if code == 404:
                return None
            if code == 200 and corps:
                if _methode["ok"] != m:
                    dm.log(f"  (methode de telechargement : {m})")
                    _methode["ok"] = m
                return corps.decode("utf-8", "replace")
            erreurs.append(f"{m}: HTTP {code}")
        time.sleep(3 * (tour + 1))
    dm.log(f"  echec : {url}")
    for e in erreurs[-3:]:
        dm.log(f"     {e}")
    return None


def liens_doctrine(html):
    res = []
    for h in RE_HREF.findall(html or ""):
        h = h.replace(BASE, "")
        if RE_PAGE.match(h) and h not in res:
            res.append(h)
    return res


def telecharger(args=None):
    os.makedirs(DOSSIER, exist_ok=True)
    file_ = [RACINE + t + ".html" for t in THEMES] + [RACINE + "plan-du-site.html"]
    vus, pages = set(), []
    dm.log("Telechargement du BOSS (boss.gouv.fr)…")
    while file_ and len(vus) < 400:
        chemin = file_.pop(0)
        if chemin in vus:
            continue
        vus.add(chemin)
        html = obtenir(BASE + chemin)
        time.sleep(PAUSE)
        if html is None:
            continue
        for l in liens_doctrine(html):
            if l not in vus and l not in file_:
                file_.append(l)
        if chemin.endswith("plan-du-site.html"):
            continue
        cible = os.path.join(DOSSIER, chemin[len(RACINE):])
        os.makedirs(os.path.dirname(cible) or DOSSIER, exist_ok=True)
        with open(cible + ".tmp", "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
        os.replace(cible + ".tmp", cible)
        pages.append(chemin)
        if len(pages) % 10 == 0:
            dm.log(f"  {len(pages)} pages…")
    dm.log(f"{len(pages)} pages enregistrees dans {DOSSIER}")
    return len(pages)


# --------------------------------------------------------------------------- analyse du HTML

VIDES = {"br", "hr", "img", "input", "meta", "link", "col", "area", "base", "wbr", "source", "track", "embed", "param"}
IGNORES = {"script", "style", "noscript", "template", "svg", "head"}


class Noeud:
    __slots__ = ("tag", "attrs", "enfants", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.enfants, self.parent = tag, attrs or {}, [], parent

    def classes(self):
        return (self.attrs.get("class") or "").split()


class Arbre(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.racine = Noeud("#racine")
        self.cur = self.racine

    def handle_starttag(self, tag, attrs):
        n = Noeud(tag, dict(attrs), self.cur)
        self.cur.enfants.append(n)
        if tag not in VIDES:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.enfants.append(Noeud(tag, dict(attrs), self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.enfants.append(data)


def arbre(html):
    a = Arbre()
    a.feed(html)
    a.close()
    return a.racine


def trouver(n, tag, pred=None):
    if isinstance(n, str):
        return None
    if n.tag == tag and (pred is None or pred(n)):
        return n
    for c in n.enfants:
        r = trouver(c, tag, pred)
        if r is not None:
            return r
    return None


def propre(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def texte(n):
    if isinstance(n, str):
        return n
    if n.tag in IGNORES:
        return ""
    if n.tag == "br":
        return " "
    return "".join(texte(c) for c in n.enfants)


def liste(n, niveau=0):
    """Lignes d'une liste ul/ol (listes imbriquees indentees)."""
    res = []
    for li in n.enfants:
        if isinstance(li, str) or li.tag != "li":
            continue
        direct = "".join(texte(c) for c in li.enfants if isinstance(c, str) or c.tag not in ("ul", "ol"))
        if propre(direct):
            res.append("  " * niveau + "- " + propre(direct))
        for c in li.enfants:
            if not isinstance(c, str) and c.tag in ("ul", "ol"):
                res += liste(c, niveau + 1)
    return res


def lignes_tableau(n):
    res = []

    def rangees(x):
        if isinstance(x, str):
            return
        if x.tag == "tr":
            cellules = [propre(texte(c)) for c in x.enfants if not isinstance(c, str) and c.tag in ("td", "th")]
            if any(cellules):
                res.append(" | ".join(cellules))
            return
        for c in x.enfants:
            rangees(c)

    rangees(n)
    return res


def evenements(n, sortie, prefixe=""):
    """Parcours dans l'ordre du document : ('h', niveau, texte), ('par', numero), ('bloc', texte)."""
    for c in n.enfants:
        if isinstance(c, str):
            t = propre(c)
            if t:
                sortie.append(("bloc", prefixe + t))
                prefixe = ""
            continue
        t, cl = c.tag, c.classes()
        if t in IGNORES or "bloc_notes_version" in cl:
            continue
        if t in ("h1",):
            continue
        if t in ("h2", "h3", "h4", "h5", "h6"):
            titre = propre(texte(c))
            if titre:
                sortie.append(("h", int(t[1]), titre))
        elif t == "span" and "paragraphe" in cl:
            sortie.append(("par", propre(texte(c))))
        elif t in ("ul", "ol"):
            for l in liste(c):
                sortie.append(("bloc", l))
        elif t == "table":
            for l in lignes_tableau(c):
                sortie.append(("bloc", l))
        elif t == "p":
            tx = propre(texte(c))
            if tx:
                sortie.append(("bloc", prefixe + tx))
                prefixe = ""
        elif t in ("div", "section", "aside", "blockquote", "details", "figure") or "bloc_" in " ".join(cl):
            etiquette = ""
            if "bloc_important" in cl:
                etiquette = "Important : "
            elif "bloc_exemple" in cl:
                etiquette = "Exemple : "
            evenements(c, sortie, etiquette)
        else:   # span, strong, a, ... au niveau d'un bloc : texte en ligne
            tx = propre(texte(c))
            if tx:
                sortie.append(("bloc", prefixe + tx))
                prefixe = ""


def decouper_ligne(ligne, maxi=MAX_CHUNK):
    morceaux = []
    while len(ligne) > maxi:
        coupe = max(ligne.rfind(". ", 0, maxi), ligne.rfind("; ", 0, maxi), ligne.rfind(" ", 0, maxi))
        coupe = coupe if coupe > maxi // 3 else maxi
        morceaux.append(ligne[:coupe + 1].strip())
        ligne = ligne[coupe + 1:].strip()
    if ligne:
        morceaux.append(ligne)
    return morceaux


def analyser_page(html):
    """-> dict(titre, maj, chunks=[(titre_chemin, par, texte)]) ou None si la page n'a pas de doctrine."""
    rac = arbre(html)
    main = trouver(rac, "main") or rac
    art = trouver(main, "article") or main
    h1 = trouver(art, "h1") or trouver(main, "h1")
    titre = propre(texte(h1)) if h1 else ""
    if not titre:
        t = trouver(rac, "title")
        titre = re.sub(r"\s*[-|]\s*Boss\.gouv\.fr\s*$", "", propre(texte(t)), flags=re.I) if t else ""
    evts = []
    evenements(art, evts)
    brut = propre(texte(art))
    m = re.search(r"(?:Mis à jour|Publié) le (\d{2})/(\d{2})/(\d{4})", brut)
    maj = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""
    # rescrit individuel : « Numero : BOSS-RES-000006 » + question / reponse
    q = trouver(art, "div", lambda x: "bloc_question" in x.classes())
    num = re.search(r"BOSS-RES-\d+", brut)
    if q is not None and num:
        titre = f"Rescrit {num.group(0)} — {propre(texte(q))[:160]}"
    if not any(e[0] == "bloc" for e in evts) or len(brut) < 150:
        return None

    heads, par, cour = {}, None, None
    unites = []      # [chemin, par, [lignes]] une unite = un paragraphe numerote
    for e in evts:
        if e[0] == "h":
            for k in [k for k in heads if k >= e[1]]:
                del heads[k]
            heads[e[1]] = e[2]
            cour, par = None, None
        elif e[0] == "par":
            par, cour = e[1], None
        else:
            chemin = " > ".join(heads[k] for k in sorted(heads))
            if cour is None:
                cour = [chemin, par, []]
                unites.append(cour)
            cour[2].append(e[1])

    chunks, actuel = [], None   # actuel = [chemin, [paragraphes], [lignes], taille]

    def clore():
        nonlocal actuel
        if actuel and actuel[2]:
            pars = [p for p in actuel[1] if p]
            rng = "" if not pars else (pars[0] if pars[0] == pars[-1] else f"{pars[0]}-{pars[-1]}")
            chunks.append((actuel[0], rng, "\n".join(actuel[2])))
        actuel = None

    for chemin, p, lignes in unites:
        for i, l in enumerate(lignes):
            for morceau in decouper_ligne(l):
                if actuel and (actuel[0] != chemin or actuel[3] + len(morceau) > TAILLE_CHUNK):
                    clore()
                if actuel is None:
                    actuel = [chemin, [], [], 0]
                if p and (not actuel[2] or (i == 0 and (not actuel[1] or actuel[1][-1] != p))):
                    morceau = f"[§ {p}] {morceau}"
                if p and (not actuel[1] or actuel[1][-1] != p):
                    actuel[1].append(p)
                actuel[2].append(morceau)
                actuel[3] += len(morceau) + 1
    clore()
    total = sum(len(c[2]) for c in chunks)
    if total < 150:
        return None
    return {"titre": titre, "maj": maj, "chunks": chunks}


# --------------------------------------------------------------------------- index

SCHEMA = """
DROP TABLE IF EXISTS fts;
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS docs;
DROP TABLE IF EXISTS meta;
CREATE TABLE docs(id TEXT PRIMARY KEY, source TEXT, type TEXT, serie TEXT, division TEXT,
  titre TEXT, debut TEXT, url TEXT, nb INTEGER);
CREATE TABLE chunks(id INTEGER PRIMARY KEY, doc TEXT, n INTEGER, par TEXT, titre TEXT, texte TEXT);
CREATE INDEX chunks_doc ON chunks(doc, n);
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
CREATE VIRTUAL TABLE fts USING fts5(titre, texte, content='chunks', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2');
"""


def fichiers_html():
    res = []
    for racine, _, noms in os.walk(DOSSIER):
        for nom in noms:
            if nom.endswith(".html"):
                res.append(os.path.join(racine, nom))
    return sorted(res)


def construire(args=None):
    fichiers = fichiers_html()
    if not fichiers:
        raise RuntimeError("Aucune page dans donnees\\boss : lancer d'abord telecharger_boss.bat.")
    tmp = DB + ".new"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    n_docs = n_chunks = 0
    ignores = []
    for f in fichiers:
        rel = os.path.relpath(f, DOSSIER).replace(os.sep, "/")
        chemin = rel[:-5]
        theme = chemin.split("/")[0]
        with open(f, encoding="utf-8", errors="replace") as fh:
            page = analyser_page(fh.read())
        if not page or not page["chunks"]:
            ignores.append(rel)
            continue
        ident = "BOSS-" + chemin.replace("/", "-")
        titre_page = page["titre"] or chemin
        genre = {"rescrits": "Rescrit", "table-des-parametres": "Parametres"}.get(theme, "Contenu")
        con.execute("INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?)",
                    (ident, "BOSS", genre, theme, LIBELLES.get(theme, theme),
                     f"{LIBELLES.get(theme, theme)} — {titre_page}", page["maj"],
                     f"{BASE}{RACINE}{chemin}.html", len(page["chunks"])))
        for i, (chem, par, tx) in enumerate(page["chunks"], 1):
            con.execute("INSERT INTO chunks(doc,n,par,titre,texte) VALUES (?,?,?,?,?)",
                        (ident, i, par, f"{titre_page} > {chem}" if chem else titre_page, tx))
            n_chunks += 1
        n_docs += 1
    con.execute("INSERT INTO fts(rowid,titre,texte) SELECT id,titre,texte FROM chunks")
    con.execute("INSERT INTO fts(fts) VALUES('optimize')")
    for k, v in (("boss_construit_le", time.strftime("%Y-%m-%d %H:%M")), ("boss_documents", str(n_docs)),
                 ("boss_passages", str(n_chunks))):
        con.execute("INSERT INTO meta VALUES (?,?)", (k, v))
    con.commit()
    con.execute("VACUUM")
    con.close()
    os.replace(tmp, DB)
    dm.log(f"BOSS : {n_docs} pages, {n_chunks} passages ({os.path.getsize(DB) / 1e6:.1f} Mo)"
           + (f" ; {len(ignores)} page(s) sans doctrine ignoree(s)" if ignores else ""))
    return n_docs, n_chunks


def mise_a_jour(args=None):
    telecharger(args)
    construire(args)


# --------------------------------------------------------------------------- recherche

def ouvrir():
    if not os.path.exists(DB):
        raise RuntimeError("L'index du BOSS n'existe pas encore : lancer « mettre_a_jour_boss.bat ».")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def candidats(con, mots, serie, minimum):
    sql = """SELECT c.id FROM fts JOIN chunks c ON c.id = fts.rowid JOIN docs d ON d.id = c.doc
             WHERE fts MATCH ?"""
    if serie:
        sql += " AND d.serie = ?"
    else:   # mesures exceptionnelles anciennes (2021, covid) : seulement si le theme est demande
        sql += " AND NOT (d.serie = 'mesures-exceptionnelles' AND d.debut < '2024-01-01')"
    sql += " ORDER BY bm25(fts, 3.0, 1.0) LIMIT 200"
    trouves = []
    for mode in ("et", "ou"):
        p = [dm.requete_fts(mots, mode)] + ([serie] if serie else [])
        for l in con.execute(sql, p).fetchall():
            if l["id"] not in trouves:
                trouves.append(l["id"])
        if len(trouves) >= minimum:
            break
    return trouves


def date_page(debut, genre):
    if not debut:
        return "Date de mise a jour non indiquee"
    return ("Publie le " if genre == "Rescrit" else "Mis a jour le ") + debut


def code_theme(valeur):
    if not valeur:
        return None
    v = dm.sans_accents(str(valeur).strip().lower()).replace(" ", "-").replace("'", "")
    if v in ("", "null", "none", "tous"):
        return None
    for t in THEMES:
        if v == t or v in t or t.startswith(v):
            return t
    return None


RE_PARTICULIER = re.compile(
    r"electrique|hydrogene|hybride rechargeable|a titre derogatoire|derogation|mesure exceptionnelle|"
    r"jusqu.au 31 decembre 20\d\d|entre le 1er \w+ 20\d\d et le 31 decembre 20\d\d|"
    r"(?:du|au) 1er janvier 20(?:2[0-4])")


RE_ANCIEN = re.compile(r"\bavant le (?:\d+(?:er)? )?(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre) 20\d\d|"
                      r"\bavant le 1er janvier 20\d\d")


def cas_particulier(texte, titre):
    """Vrai si le passage traite d'un cas particulier ou temporaire (a ne pas servir comme regle generale)."""
    return bool(RE_PARTICULIER.search(dm.sans_accents((titre or "") + " " + (texte or "")).lower()))


def chercher(requete, serie=None, limite=3):
    con = ouvrir()
    limite = dm.entier(limite, 3, 1, 4)
    theme = code_theme(serie)
    mots = dm.jetons(requete)
    if not mots:
        con.close()
        return "Requete vide : donne quelques mots-cles (ex. « avantage en nature vehicule »)."
    racines = [dm.racine(m) for m in mots]
    q_particulier = cas_particulier(requete, "")
    q_norm = dm.sans_accents(requete).lower()
    q_avant = bool(re.search(r"\bavant\b|ancien|anterieur|2024|2023|2022", q_norm))
    q_niche = bool(re.search(r"particulier|constructeur|concessionnaire", q_norm))
    ids = candidats(con, mots, theme, max(limite * 8, 30))
    if not ids:
        con.close()
        return "Aucun resultat dans le BOSS. Essaie d'autres mots-cles."
    notes = []
    for rang, cid in enumerate(ids):
        c = con.execute("SELECT c.*, d.titre AS dtitre, d.debut, d.url, d.nb, d.type AS dtype, d.serie AS dserie "
                        "FROM chunks c JOIN docs d ON d.id = c.doc WHERE c.id=?", (cid,)).fetchone()
        dist, tot = dm.couverture(racines, dm.mots_normalises(c["texte"]))
        tdist, _ = dm.couverture(racines, dm.mots_normalises(c["titre"]))
        sc = dist * 10 + min(tot, 8) * 0.4 + tdist * 4 - rang * 0.1
        if c["dserie"] == "table-des-parametres":
            sc += 9        # valeurs de reference (plafond, SMIC, seuils) : a privilegier
        if "Exemple" in c["texte"]:
            sc -= 4        # la regle avant l'exemple
        if cas_particulier(c["texte"], c["titre"]) and not q_particulier:
            sc -= 9        # cas particulier (vehicule electrique, mesure temporaire...) : apres la regle generale
        t_norm = dm.sans_accents(c["titre"]).lower()
        if not q_avant and RE_ANCIEN.search(t_norm):
            sc -= 9        # regime remplace (« avant le 1er fevrier 2025 ») : le regime en vigueur d'abord
        if not q_niche and "cas particulier" in t_norm:
            sc -= 6        # ex. constructeurs et concessionnaires : pas la regle generale
        sc += max(0, 5 - c["titre"].count(">")) * 1.0   # passages d'ensemble avant les sous-sous-cas
        prec = con.execute("SELECT titre FROM chunks WHERE doc=? AND n=?", (c["doc"], c["n"] - 1)).fetchone()
        if prec is None or prec["titre"] != c["titre"]:
            sc += 4        # premier passage sous son intertitre : c'est la regle posee, avant les details
        notes.append([sc, c])
    choisis = []
    while notes and len(choisis) < limite:
        def ajuste(x):
            sc, c = x
            for d in choisis:
                if d["doc"] == c["doc"]:
                    sc -= 5 if abs(d["n"] - c["n"]) <= 1 else 2
            return sc
        meilleur = max(notes, key=ajuste)
        notes.remove(meilleur)
        choisis.append(meilleur[1])
    sorties, extraits = [], []
    for i, c in enumerate(choisis, 1):
        en_tete = f"[{i}] {c['doc']}"
        if c["par"]:
            en_tete += f" — § {c['par']}"
        en_tete += f" (passage {c['n']}/{c['nb']})"
        ext = (c["texte"] if len(c["texte"]) <= 800 and limite <= 3
               else dm.extrait(c["texte"], racines, MAX_EXTRAIT if limite <= 3 else 480))
        extraits.append(ext)
        sorties.append(f"{en_tete}\n{c['dtitre']}\n{c['titre'].split(' > ', 1)[-1] if ' > ' in c['titre'] else ''}\n"
                       f"{date_page(c['debut'], c['dtype'])} · {c['url']}\n{ext}".replace("\n\n", "\n"))
    pied = (dm.verifier_chiffres(requete, extraits)
            + f"\n---\nBOSS (boss.gouv.fr, base du {dm.meta(con, 'boss_construit_le')[:10]}). Doctrine administrative : "
            "verifie que ces passages confirment ce que dit l'utilisateur ; sinon, dis-le. "
            "Cite uniquement ces references (identifiant + §) ; « passage N/M » est un numero interne, jamais un §. Si ces passages ne couvrent qu'un cas particulier "
            "(ex. vehicule electrique), ne generalise pas : relance une recherche. "
            "Suite : lire_document(identifiant, passage).")
    con.close()
    return "\n\n".join(sorties) + pied


def lire(identifiant, passage=1, nombre=2):
    con = ouvrir()
    ident = (identifiant or "").strip()
    d = con.execute("SELECT * FROM docs WHERE upper(id)=upper(?)", (ident,)).fetchone()
    if not d:
        voisins = con.execute("SELECT id, titre FROM docs WHERE upper(id) LIKE upper(?) ORDER BY id LIMIT 15",
                              ("%" + ident.replace("BOSS-", "") + "%",)).fetchall() or \
            con.execute("SELECT id, titre FROM docs ORDER BY id LIMIT 40").fetchall()
        con.close()
        return "Identifiants BOSS disponibles :\n" + "\n".join(f"- {v['id']} : {v['titre'][:100]}" for v in voisins)
    passage = dm.entier(passage, 1, 1, 10000)
    nombre = dm.entier(nombre, 2, 1, 3)
    rows = con.execute("SELECT n, titre, texte FROM chunks WHERE doc=? AND n>=? AND n<? ORDER BY n",
                       (d["id"], passage, passage + nombre)).fetchall()
    con.close()
    if not rows:
        return f"{d['id']} n'a que {d['nb']} passages."
    corps, taille, dernier = [], 0, passage - 1
    for r in rows:
        bloc = f"(passage {r['n']}/{d['nb']}) {r['titre'].split(' > ', 1)[-1] if ' > ' in r['titre'] else ''}\n{r['texte']}"
        if corps and taille + len(bloc) > MAX_LECTURE:
            break
        corps.append(bloc)
        taille += len(bloc)
        dernier = r["n"]
    suite = f"\n\n[Suite : lire_document(\"{d['id']}\", passage={dernier + 1})]" if dernier < d["nb"] else ""
    return (f"{d['id']} — {d['titre']}\n{date_page(d['debut'], d['type'])} · {d['url']}\n\n"
            + "\n\n".join(corps) + suite)


def info():
    try:
        con = ouvrir()
        s = (f"BOSS : {dm.meta(con, 'boss_documents')} pages, {dm.meta(con, 'boss_passages')} passages, "
             f"construit le {dm.meta(con, 'boss_construit_le')}")
        con.close()
        return s
    except Exception as e:  # noqa: BLE001
        return f"BOSS : non disponible ({e})"
