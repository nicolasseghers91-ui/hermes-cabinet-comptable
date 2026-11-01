# -*- coding: utf-8 -*-
"""Tableaux de bord de gestion calcules a partir d'un FEC (N et, si fourni, N-1), pour tous les types de dossiers.

Tout est calcule en Python (aucun chiffre n'est produit par le modele). Le resultat est une page HTML autonome
(Chart.js via CDN) aux couleurs du cabinet, plus un court resume texte que le modele peut commenter.

Types : bic, bnc, sci_ir, sci_is, association, esms.
Conventions du cabinet : CA = 706 + 707 + 708 ; resultat net = classe 7 - classe 6 ; tous les % ont pour base le CA
(BIC) ou le total des produits / ressources / recettes pour les autres types, precise dans chaque tableau.
"""
import collections
import datetime
import html
import json
import os
import re

import controle_fec as cf

ICI = os.path.dirname(os.path.abspath(__file__))

TYPES = {
    "bic": "BIC (SAS, SARL, EURL, EI)",
    "bnc": "BNC (professions libérales)",
    "sci_ir": "SCI à l'IR",
    "sci_is": "SCI à l'IS",
    "association": "Association loi 1901",
    "esms": "Association ESMS (établissement social ou médico-social)",
}
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
NUM = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"
C = {"terra": "#C45B3A", "ocre": "#D4A853", "brun": "#3D2B1F", "fond": "#FEFCF8", "sable": "#F5F0E8",
     "vert": "#6B8E4E", "ambre": "#E8A535", "rouge": "#B83230", "bleu": "#4A6FA5"}


# --------------------------------------------------------------------------- series mensuelles

class Ser:
    """Serie mensuelle avec arithmetique terme a terme."""

    def __init__(self, v):
        self.v = [float(x) for x in v]

    def _o(self, o):
        return o.v if isinstance(o, Ser) else [o] * len(self.v)

    def __add__(self, o):
        return Ser(a + b for a, b in zip(self.v, self._o(o)))

    __radd__ = __add__

    def __sub__(self, o):
        return Ser(a - b for a, b in zip(self.v, self._o(o)))

    def __mul__(self, k):
        return Ser(a * k for a in self.v)

    def __neg__(self):
        return Ser(-a for a in self.v)

    def clip0(self):
        return Ser(max(0.0, a) for a in self.v)

    @property
    def cum(self):
        return sum(self.v)

    def run(self):
        """Cumul progressif (soldes de bilan en fin de mois)."""
        t, r = 0.0, []
        for a in self.v:
            t += a
            r.append(t)
        return Ser(r)


CLOTURES = {"CLO", "CL", "CLOT", "CLOTURE", "CLÔTURE", "ODCL", "OD-CLO", "CLS"}
AN_CODES = {"AN", "RAN", "A-N", "ANO", "ANOUV", "A NOUVEAU", "ANX", "RAN1"}


class Jeu:
    """Ecritures d'un exercice agregees par compte et par mois (solde = debit - credit).

    Les mois sont continus du premier au dernier mois du fichier ; `nb_mois` tronque ou complete par des mois vides.
    Les ecritures de cloture (virement des classes 6/7) sont ignorees."""

    def __init__(self, lignes, arrete=None, nb_mois=None):
        sel = [l for l in lignes if l["date"] and (not arrete or l["date"] <= arrete)
               and not (l["j"].upper() in CLOTURES and l["cpt"][:1] in ("6", "7"))]
        self.vide = not sel
        self.debut = min((l["date"] for l in sel), default=None)
        self.fin = max((l["date"] for l in sel), default=None)
        self.mois, self.incomplet = [], False
        if sel:
            a, m = self.debut.year, self.debut.month
            while (a, m) <= (self.fin.year, self.fin.month):
                self.mois.append((a, m))
                a, m = (a + 1, 1) if m == 12 else (a, m + 1)
            if nb_mois:
                self.incomplet = nb_mois > len(self.mois)
                self.mois = self.mois[:nb_mois]
                while len(self.mois) < nb_mois:
                    a, m = self.mois[-1]
                    self.mois.append((a + 1, 1) if m == 12 else (a, m + 1))
        pos = {m: i for i, m in enumerate(self.mois)}
        self.n = len(self.mois)
        self.net = collections.defaultdict(lambda: [0.0] * self.n)
        self.lib = {}
        self.ouv = collections.defaultdict(float)   # soldes d'ouverture (journal d'a-nouveaux), compris dans `net`
        self.mvt = collections.defaultdict(lambda: [0.0] * self.n)   # mouvements de la periode, hors a-nouveaux
        for l in sel:
            i = pos.get((l["date"].year, l["date"].month))
            if i is None:
                continue
            self.net[l["cpt"]][i] += float(l["d"] - l["c"])
            if l["j"].upper() in AN_CODES:
                self.ouv[l["cpt"]] += float(l["d"] - l["c"])
            else:
                self.mvt[l["cpt"]][i] += float(l["d"] - l["c"])
            if l["cptlib"] and l["cpt"] not in self.lib:
                self.lib[l["cpt"]] = l["cptlib"]

    def comptes(self, prefixes, exclure=()):
        return sorted(c for c in self.net if c.startswith(tuple(prefixes)) and not c.startswith(tuple(exclure)))

    def ser(self, prefixes, sens=1, exclure=()):
        tot = [0.0] * self.n
        for c in self.comptes(prefixes, exclure):
            for i, x in enumerate(self.net[c]):
                tot[i] += x
        return Ser(tot) * sens

    def ser_mvt(self, prefixes, sens=1, exclure=()):
        """Comme `ser` mais sans les a-nouveaux (flux de la periode : capital rembourse, variation de stock...)."""
        tot = [0.0] * self.n
        for c in sorted(c for c in self.mvt if c.startswith(tuple(prefixes)) and not c.startswith(tuple(exclure))):
            for i, x in enumerate(self.mvt[c]):
                tot[i] += x
        return Ser(tot) * sens

    def ouverture(self, prefixes):
        """Total des a-nouveaux sur les comptes demandes (pour isoler la variation de la periode)."""
        return sum(v for c, v in self.ouv.items() if c.startswith(tuple(prefixes)))

    def ser_compte(self, c, sens=1):
        return Ser(self.net[c]) * sens if c in self.net else Ser([0.0] * self.n)

    def libelle_mois(self, i):
        a, m = self.mois[i]
        return f"{MOIS[m - 1]} {str(a)[2:]}"


# --------------------------------------------------------------------------- formats

def fm(x, dec=0):
    if x is None:
        return "—"
    s = f"{abs(x):,.{dec}f}".replace(",", " ").replace(".", ",")
    if round(x, dec) == 0:
        return s
    return ("−" if x < 0 else "") + s


def pc(x, dec=1):
    if x is None:
        return "—"
    if round(x, dec) == 0:
        x = 0.0
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",").replace("-", "−") + " %"


def part(a, b):
    return None if not b else a / b * 100


def evol(a, b):
    """Variation en % de b (reference) vers a ; None si la reference est nulle."""
    return None if not b else (a - b) / abs(b) * 100


def evol_s(a, b, plafond=1000):
    """Variation affichable : None (« n.s. ») si la reference est nulle, si le signe s'inverse (ex. charges nettes
    negatives vs positives) ou si l'ecart depasse `plafond` % — un pourcentage y serait trompeur."""
    if a is None or b is None or not b:
        return None
    if a * b < 0:
        return None
    v = evol(a, b)
    return None if v is None or abs(v) > plafond else v


def e(s):
    return html.escape(str(s))


def var_cell(a, b, bon=True, seuil=30):
    """Cellule de variation a vs b (reference) : « — » si rien a comparer, « n.s. » si la reference est nulle."""
    if b is None or (abs(a) < 0.005 and abs(b) < 0.005):
        return "—"
    return badge(evol_s(a, b) if abs(b) >= 0.005 else None, bon, seuil)


def badge(v, bon_si_hausse=True, seuil=30):
    if v is None:
        return '<span class="badge b-blue">n.s.</span>'
    bon = (v >= 0) == bon_si_hausse
    cls = "b-green" if bon else ("b-red" if abs(v) >= seuil else "b-amber")
    if abs(v) < 0.05:
        cls = "b-blue"
    return f'<span class="badge {cls}">{"+" if v > 0 else ""}{pc(v)}</span>'


# --------------------------------------------------------------------------- rendu HTML

class Rendu:
    def __init__(self, has_n1):
        self.charts = {}
        self.has_n1 = has_n1
        self.nc = 0

    def canvas(self, spec, hauteur=260):
        self.nc += 1
        cid = f"cv{self.nc}"
        self.charts[cid] = spec
        return f'<div class="chartbox" style="height:{hauteur}px"><canvas id="{cid}"></canvas></div>'

    @staticmethod
    def cartes(items):
        h = '<div class="grid">'
        for titre, valeur, sous, cls in items:
            h += f'<div class="card {cls}"><div class="lbl">{e(titre)}</div><div class="big">{valeur}</div><div class="sub">{sous}</div></div>'
        return h + "</div>"

    @staticmethod
    def table(entetes, lignes, note=""):
        h = '<div class="tw"><table><thead><tr>' + "".join(f"<th>{e(x)}</th>" for x in entetes) + "</tr></thead><tbody>"
        for cls, cells in lignes:
            h += f'<tr class="{cls}">' + "".join(
                (f"<td>{c}</td>" if i else f"<td class=\"l\">{c}</td>") for i, c in enumerate(cells)) + "</tr>"
        h += "</tbody></table></div>"
        if note:
            h += f'<p class="note">{e(note)}</p>'
        return h

    @staticmethod
    def box(kind, titre, items):
        li = "".join(f"<li>{x}</li>" for x in items)
        return f'<div class="box box-{kind}"><strong>{e(titre)}</strong><ul class="box-list">{li}</ul></div>'


def spec_bar(labels, datasets, horizontal=False, empile=False, unite="€"):
    return {"type": "bar", "labels": labels, "datasets": datasets, "horizontal": horizontal, "stacked": empile, "unite": unite}


def spec_line(labels, datasets, unite="€"):
    return {"type": "line", "labels": labels, "datasets": datasets, "unite": unite}


def spec_donut(labels, data):
    pal = [C["terra"], C["ocre"], C["vert"], C["bleu"], C["ambre"], C["rouge"], C["brun"], "#9C8B7A"]
    return {"type": "doughnut", "labels": labels, "datasets": [{"data": data, "backgroundColor": pal[:len(data)]}]}


def ds(label, data, couleur, **kw):
    d = {"label": label, "data": [round(x, 2) for x in data], "backgroundColor": couleur, "borderColor": couleur}
    d.update(kw)
    return d


# --------------------------------------------------------------------------- noyau de calcul

def calculs_bic(J):
    """Cascade PCG (SIG). Controle : resultat net = classe 7 - classe 6."""
    k = {}
    k["ca"] = J.ser(("70",), -1)                      # 701 a 708, nets des rabais 709 (= 706+707+708 si 701-705 absents)
    k["prod_st"] = J.ser(("71", "72"), -1)            # production stockee et immobilisee
    k["conso"] = J.ser(("60",), 1, exclure=("606",))
    k["marge"] = k["ca"] + k["prod_st"] - k["conso"]
    k["ext"] = J.ser(("606", "61", "62"), 1)
    k["va"] = k["marge"] - k["ext"]
    k["sub"] = J.ser(("74",), -1)
    k["pers"] = J.ser(("64",), 1)
    k["impots"] = J.ser(("63",), 1)
    k["ebe"] = k["va"] + k["sub"] - k["pers"] - k["impots"]
    k["dot"] = J.ser(("68",), 1)
    k["autres_ch"] = J.ser(("65",), 1)
    k["c7"] = J.ser(("7",), -1)
    k["c6"] = J.ser(("6",), 1)
    k["fin"] = J.ser(("76",), -1) - J.ser(("66",), 1)
    k["exc"] = J.ser(("77",), -1) - J.ser(("67",), 1)
    k["is"] = J.ser(("69",), 1)
    autres_pr = k["c7"] - k["ca"] - k["prod_st"] - k["sub"] - J.ser(("76",), -1) - J.ser(("77",), -1)
    k["autres_pr"] = autres_pr
    k["rex"] = k["ebe"] - k["dot"] - k["autres_ch"] + autres_pr
    k["rn"] = k["rex"] + k["fin"] + k["exc"] - k["is"]
    k["ecart_controle"] = (k["rn"] - (k["c7"] - k["c6"])).cum
    return k


def treso_bfr(J):
    t = {}
    t["treso"] = J.ser(("512", "514", "53", "519", "511"), 1).run()
    t["clients"] = J.ser(("411", "413", "416", "418", "491"), 1).run()
    t["stocks"] = J.ser(("31", "32", "33", "34", "35", "36", "37", "39"), 1).run()
    t["fournisseurs"] = J.ser(("401", "403", "408"), -1).run()
    t["bfr"] = t["clients"] + t["stocks"] - t["fournisseurs"]
    return t


# --------------------------------------------------------------------------- briques d'onglets

class Ctx:
    """Tout ce dont les onglets ont besoin."""

    def __init__(self, J, J1, typ, nom, opts):
        self.J, self.J1, self.typ, self.nom, self.opts = J, J1, typ, nom, opts
        self.R = Rendu(J1 is not None)
        self.n = J.n
        self.labels = [J.libelle_mois(i) for i in range(J.n)]
        self.vig = []   # points de vigilance (niveau, texte)

    def n1(self, f):
        return f(self.J1) if self.J1 is not None else None

    def vigil(self, niveau, texte):
        self.vig.append((niveau, texte))


def ligne_cumul(cx, label, serN, serN1, base, sens_bon=True, cls="", mois_aff=None):
    """[libelle, dernier mois, cumul, %base, N-1 cumul, variation]"""
    cum = serN.cum
    cells = [e(label), fm(serN.v[-1]) if serN.v else "—", fm(cum), pc(part(cum, base))]
    if cx.R.has_n1:
        c1 = serN1.cum if serN1 is not None else None
        cells += [fm(c1), var_cell(cum, c1, sens_bon)]
    return (cls, cells)


def entetes_cumul(cx, base_label="% CA"):
    h = ["Poste", "Dernier mois", "Cumul", base_label]
    if cx.R.has_n1:
        h += ["N-1 (même période)", "Variation"]
    return h


def lignes_comptes(cx, prefixes, sens, base, exclure=(), sens_bon=True, seuil=0.0):
    rows = []
    for c in cx.J.comptes(prefixes, exclure):
        sN = cx.J.ser_compte(c, sens)
        if abs(sN.cum) < 0.005 and not any(abs(x) > 0.005 for x in sN.v):
            continue
        s1 = cx.J1.ser_compte(c, sens) if cx.J1 is not None else None
        rows.append(ligne_cumul(cx, f"{c} {cx.J.lib.get(c, '')[:34]}", sN, s1, base, sens_bon))
    return rows


def onglet_tableau_cumul(cx, categories, base, base_label, total_lignes):
    """categories: [(titre, [(label, prefixes, sens, exclure)], sens_bon)] ; total_lignes: [(label, serN, serN1, cls, sens_bon)]"""
    rows = []
    for titre, postes, sens_bon in categories:
        rows.append(("rcat", [f"<strong>{e(titre)}</strong>"] + [""] * (len(entetes_cumul(cx, base_label)) - 1)))
        sous_n, sous_1 = Ser([0.0] * cx.n), (Ser([0.0] * cx.n) if cx.J1 is not None else None)
        for label, prefixes, sens, excl in postes:
            sN = cx.J.ser(prefixes, sens, excl)
            s1 = cx.J1.ser(prefixes, sens, excl) if cx.J1 is not None else None
            if abs(sN.cum) < 0.005 and (s1 is None or abs(s1.cum) < 0.005):
                continue
            rows.append(ligne_cumul(cx, label, sN, s1, base, sens_bon))
        # detail par compte repliable : on garde les comptes les plus significatifs seulement
    for label, sN, s1, cls, sens_bon in total_lignes:
        rows.append(ligne_cumul(cx, label, sN, s1, base, sens_bon, cls))
    return cx.R.table(entetes_cumul(cx, base_label), rows)


def bloc_mensuel(cx, titre, serN, serN1, couleur_n, sens_bon=True):
    ds_list = [ds(f"N", serN.v, couleur_n)]
    if serN1 is not None:
        ds_list.append(ds("N-1", serN1.v, "#B9AFA2"))
    return f"<h3>{e(titre)}</h3>" + cx.R.canvas(spec_bar(cx.labels, ds_list))


def tableau_mensuel(cx, lignes, base=None, base_label="% base", sens_bon_defaut=True):
    """lignes: [(label, serN, serN1, cls, sens_bon)] -> tableau mois par mois + cumul + % + N-1 + variation."""
    ent = ["Poste"] + cx.labels + ["Cumul", base_label] + (["N-1", "Variation"] if cx.R.has_n1 else [])
    rows = []
    for label, sN, s1, cls, sens_bon in lignes:
        cells = [e(label)] + [fm(x) for x in sN.v] + [fm(sN.cum), pc(part(sN.cum, base))]
        if cx.R.has_n1:
            c1 = s1.cum if s1 is not None else None
            cells += [fm(c1), var_cell(sN.cum, c1, sens_bon)]
        rows.append((cls, cells))
    return cx.R.table(ent, rows)


def tableau_evolution(cx, rows):
    """rows : [(label, serN, serN1|None, bon_si_hausse, cls)] -> dernier mois, M-1, variation, cumul N, cumul N-1, variation."""
    i = cx.n - 1
    ent = ["", f"{cx.labels[i]}"] + ([f"{cx.labels[i - 1]}", "M / M-1"] if cx.n > 1 else []) + ["Cumul N"] + (["Cumul N-1", "N / N-1"] if cx.R.has_n1 else [])
    out = []
    for label, sN, s1, bon, cls in rows:
        cells = [e(label), fm(sN.v[i])]
        if cx.n > 1:
            cells += [fm(sN.v[i - 1]), badge(evol_s(sN.v[i], sN.v[i - 1]), bon)]
        cells += [fm(sN.cum)]
        if cx.R.has_n1:
            c1 = s1.cum if s1 is not None else None
            cells += [fm(c1), var_cell(sN.cum, c1, bon)]
        out.append((cls, cells))
    return cx.R.table(ent, out)


def synthese(cx, cartes, rows, courbe):
    """cartes : [(titre, valeur, sous-titre, classe)] ; rows : cf. tableau_evolution ; courbe : [(label, Ser, couleur)]."""
    h = cx.R.cartes(cartes)
    h += "<h3>Évolutions : mois sur mois (M / M-1) et sur un an (N / N-1, même période)</h3>" + tableau_evolution(cx, rows)
    ds_list = [dict(ds(l, s.v, col), fill=False, tension=0.25) for l, s, col in courbe]
    h += "<h3>Courbe mensuelle</h3>" + cx.R.canvas(spec_line(cx.labels, ds_list))
    return h


# --------------------------------------------------------------------------- tresorerie / scenarios / vigilance (communs)

def onglet_tresorerie(cx, t, t1, ca_mensuel_moyen, libelle_bfr="BFR", extra="", postes=None, delai=True):
    R, i = cx.R, cx.n - 1
    cartes = [(f"Trésorerie fin {cx.labels[i]}", fm(t["treso"].v[i]) + " €", "", "card-m")]
    if cx.n > 1:
        cartes.append((f"Trésorerie fin {cx.labels[i - 1]}", fm(t["treso"].v[i - 1]) + " €", "", ""))
        cartes.append(("Évolution sur le dernier mois", fm(t["treso"].v[i] - t["treso"].v[i - 1]) + " €",
                       badge(evol_s(t["treso"].v[i], t["treso"].v[i - 1]), True), ""))
    if cx.R.has_n1 and t1:
        cartes.append((f"Même mois N-1 ({cx.labels[i]})", fm(t1["treso"].v[i]) + " €", "écart " + var_cell(t["treso"].v[i], t1["treso"].v[i], True), ""))
    h = R.cartes(cartes)
    # detail par compte
    rows = []
    for c in cx.J.comptes(("512", "514", "53", "519", "511")):
        s = cx.J.ser_compte(c).run()
        s1 = cx.J1.ser_compte(c).run() if cx.J1 is not None else None
        cells = [e(f"{c} {cx.J.lib.get(c, '')[:30]}"), fm(s.v[i])]
        if cx.R.has_n1:
            cells += [fm(s1.v[min(i, len(s1.v) - 1)] if s1 is not None else None)]
        rows.append(("", cells))
    if rows:
        h += "<h3>Détail par compte</h3>" + R.table(["Compte", f"Solde fin {cx.labels[i]}"] + (["N-1 (même mois)"] if cx.R.has_n1 else []), rows)
    # BFR
    if t is not None and "bfr" in t:
        rows = []
        for lab, k, bon in (postes or [("Créances clients (nettes de dépréciations)", "clients", True), ("Stocks", "stocks", True),
                                       ("Dettes fournisseurs", "fournisseurs", False)]) + [(libelle_bfr, "bfr", True)]:
            cells = [e(lab), fm(t[k].v[i])]
            if cx.R.has_n1:
                v1 = t1[k].v[min(i, len(t1[k].v) - 1)] if t1 else None
                cells += [fm(v1), badge(evol_s(t[k].v[i], v1) if v1 else None, False)]
            rows.append(("rh" if k == "bfr" else "", cells))
        h += f"<h3>{e(libelle_bfr)}</h3>" + R.table(["Poste", f"Fin {cx.labels[i]}"] + (["N-1", "Variation"] if cx.R.has_n1 else []), rows)
        b = t["bfr"].v[i]
        if b > 0:
            h += f'<p class="note">Couverture du BFR par la trésorerie : {pc(t["treso"].v[i] / b * 100, 0)}.</p>'
        if ca_mensuel_moyen and delai:
            jours = t["clients"].v[i] / ca_mensuel_moyen * 30
            h += (f'<p class="note">Délai de recouvrement indicatif : {fm(jours)} jours (créances / CA mensuel moyen × 30). '
                  "Créances TTC et CA HT : seule la tendance compte, pas la valeur absolue.</p>")
    ds_list = [dict(ds("Trésorerie", t["treso"].v, C["terra"]), fill=False, tension=0.25)]
    if "bfr" in t:
        ds_list.append(dict(ds(libelle_bfr, t["bfr"].v, C["ocre"]), fill=False, tension=0.25))
    h += "<h3>Évolution</h3>" + R.canvas(spec_line(cx.labels, ds_list))
    return h + extra


def scenarios(cx, ca, variables, fixes, autres, base_label="CA", titre_ca="CA", stock=None):
    """3 scenarios annuels (methode du skill) : extrapolation lineaire du cumul sur 12 mois ;
    bas = CA x 0,90 et charges variables -5 % ; haut = CA x 1,10 et charges variables +5 % ; charges fixes inchangees.
    ca, variables, fixes, autres : Ser.  Resultat = CA + autres produits - variables - fixes (avant impot sur les benefices).
    stock : Ser optionnelle (production stockee 71 - variation de stock 603, positive = stock en hausse). Elle doit etre EXCLUE de
    `variables` et `autres` : non extrapolee, elle est ajoutee a part (resultat « avec stock » = resultat + effet constate a ce jour).
    res[nom] = (CA, charges, resultat hors stock, resultat avec effet de stock a ce jour)."""
    k = 12 / cx.n
    ca_c, var_c, fix_c, aut_c = ca.cum * k, variables.cum * k, fixes.cum * k, autres.cum * k
    st = stock.cum if stock is not None and abs(stock.cum) > 0.5 else 0.0
    rows, cartes, res = [], [], {}
    for nom, fca, fvar, cls in (("Bas", 0.90, 0.95, "card"), ("Central", 1.0, 1.0, "card-m"), ("Haut", 1.10, 1.05, "card")):
        ca_s, var_s = ca_c * fca, var_c * fvar
        r = ca_s + aut_c - var_s - fix_c
        res[nom] = (ca_s, var_s + fix_c, r, r + st)
        det = f"{titre_ca} {fm(ca_s)} € · charges {fm(var_s + fix_c)} € · marge nette {pc(part(r, ca_s + aut_c))}"
        if st:
            det += f" · avec effet de stock à ce jour ({fm(st)} €) : {fm(r + st)} €"
        cartes.append((f"Scénario {nom}" + (" (hors variation de stock)" if st else ""), fm(r) + " €", det, cls))
        cells = [nom, fm(ca_s), fm(aut_c), fm(var_s), fm(fix_c), fm(r), pc(part(r, ca_s + aut_c))]
        if st:
            cells += [fm(st), fm(r + st)]
        rows.append(("", cells))
    h = cx.R.cartes(cartes)
    ent = ["Scénario", f"{titre_ca} annuel", "Autres produits", "Charges variables", "Charges fixes",
           "Résultat avant IS" + (" hors stock" if st else ""), "Marge nette"] + (["Effet de stock à ce jour", "Résultat avec effet de stock"] if st else [])
    note = (f"Extrapolation linéaire du cumul de {cx.n} mois sur 12 mois (non saisonnalisée). Bas : {titre_ca} × 0,90 et charges variables −5 % ; "
            f"haut : {titre_ca} × 1,10 et charges variables +5 % ; charges fixes inchangées. Hypothèses de simulation, pas des prévisions.")
    if st:
        note += (" Les variations de stock (production stockée 71, variation de stock 603) sont exclues de l'extrapolation : constatées à l'inventaire, "
                 "elles ne croissent pas avec l'activité. Leur effet constaté à ce jour est ajouté tel quel, sans projection, dans la dernière colonne.")
    h += cx.R.table(ent, rows, note)
    labels = ["Bas", "Central", "Haut"]
    ds_list = [ds("Résultat projeté" + (" hors variation de stock" if st else ""), [res[x][2] for x in labels], C["terra"])]
    if st:
        ds_list.append(ds("Résultat avec effet de stock à ce jour", [res[x][3] for x in labels], C["ocre"]))
    if cx.opts.get("rn_n1_annuel") is not None:
        ds_list.append(ds("Résultat N-1 (exercice complet, après IS)", [cx.opts["rn_n1_annuel"]] * 3, "#B9AFA2"))
    h += cx.R.canvas(spec_bar(labels, ds_list), 220)
    d_ca = ca_c * 0.10
    d_r = res["Haut"][2] - res["Central"][2]
    if d_ca and res["Central"][2]:
        h += cx.R.box("blue", "Effet de levier opérationnel", [
            f"+10 % de {titre_ca} (soit {fm(d_ca)} €) fait passer le résultat de {fm(res['Central'][2])} € à {fm(res['Haut'][2])} € "
            f"({'+' if d_r >= 0 else ''}{fm(d_r)} €) : les charges fixes ne bougent pas, la hausse tombe en grande partie en résultat."])
    return h, res


def onglet_vigilance(cx):
    if not cx.vig:
        return cx.R.box("green", "Points de vigilance", ["Aucun point de vigilance détecté par les contrôles automatiques."])
    h = ""
    for niveau, titre in (("red", "Alertes"), ("amber", "À surveiller"), ("blue", "Pour information")):
        items = [t for n, t in cx.vig if n == niveau]
        if items:
            h += cx.R.box(niveau, titre, items)
    return h


def variations_vigilance(cx, postes, seuil=30):
    """postes : [(label, serN, serN1, bon_si_hausse)]"""
    if cx.J1 is None:
        return
    for label, sN, s1, bon in postes:
        if s1 is None or abs(s1.cum) < 500:
            continue
        v = evol(sN.cum, s1.cum)
        if v is not None and abs(v) >= seuil:
            niveau = "red" if (v > 0) != bon else "amber"
            lisible = evol_s(sN.cum, s1.cum)
            taux = f"{'+' if v > 0 else ''}{pc(v, 0)} par rapport à N-1" if lisible is not None else "variation très forte (ou changement de signe) par rapport à N-1"
            cx.vigil(niveau, f"{e(label)} : {taux} ({fm(s1.cum)} € → {fm(sN.cum)} €).")


def anomalies_comptes(cx):
    """Soldes de sens inhabituel sur produits / charges (signalement, aucun reclassement automatique)."""
    anomalies_mensuelles(cx)
    for c in cx.J.comptes(("7",)):
        s = -cx.J.ser_compte(c).cum
        if s < -50 and not c.startswith(("709", "71", "78", "79")):
            cx.vigil("amber", f"Compte de produit {c} {e(cx.J.lib.get(c, ''))} au solde débiteur ({fm(s)} €).")
    for c in cx.J.comptes(("6",)):
        s = cx.J.ser_compte(c).cum
        if s < -50 and not c.startswith(("603", "609", "619", "629", "649")):
            cx.vigil("amber", f"Compte de charge {c} {e(cx.J.lib.get(c, ''))} au solde créditeur ({fm(s)} €).")


# --------------------------------------------------------------------------- assemblage HTML

CSS = """
:root{--terra:#C45B3A;--ocre:#D4A853;--brun:#3D2B1F;--fond:#FEFCF8;--sable:#F5F0E8;--vert:#6B8E4E;--ambre:#E8A535;--rouge:#B83230;--bleu:#4A6FA5;--ligne:#E4DAC9}
*{box-sizing:border-box}body{margin:0;background:var(--fond);color:var(--brun);font:14px/1.45 "Segoe UI",Calibri,Arial,sans-serif}
header{background:var(--brun);color:#fff;padding:18px 24px 0}header h1{margin:0;font:600 22px Georgia,serif}header p{margin:4px 0 12px;color:#E8DCC8;font-size:13px}
nav{display:flex;flex-wrap:wrap;gap:2px}nav button{background:transparent;color:#E8DCC8;border:0;padding:9px 13px;cursor:pointer;font:inherit;border-radius:6px 6px 0 0}
nav button.on{background:var(--fond);color:var(--terra);font-weight:600}main{padding:20px 24px 40px;max-width:1500px;margin:auto}
.tab{display:none}.tab.on{display:block}h2{font:600 19px Georgia,serif;color:var(--terra);margin:0 0 6px}h3{font:600 15px Georgia,serif;margin:22px 0 8px;color:var(--brun)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:12px 0}
.card{background:var(--sable);border:1px solid var(--ligne);border-left:4px solid var(--ocre);border-radius:8px;padding:12px 14px}.card-m{border-left-color:var(--terra);background:#fff}
.lbl{font-size:12px;color:#7A6A5C;text-transform:uppercase;letter-spacing:.04em}.big{font:600 24px Georgia,serif;margin:2px 0}.sub{font-size:12.5px;color:#5E4E41}
.tw{overflow-x:auto;border:1px solid var(--ligne);border-radius:8px;background:#fff}table{border-collapse:collapse;width:100%;font-size:12.5px;white-space:nowrap}
th{background:var(--brun);color:#fff;font-weight:600;padding:7px 9px;text-align:right;position:sticky;top:0}th:first-child,td.l{text-align:left}
td{padding:6px 9px;text-align:right;border-top:1px solid var(--ligne)}td.l{white-space:normal;min-width:200px}tr:nth-child(even) td{background:#FBF8F2}
tr.rt td{background:var(--sable);font-weight:700}tr.rh td{background:#F8E7D9;font-weight:700}tr.rcat td{background:var(--sable);color:var(--terra)}
.chartbox{position:relative;background:#fff;border:1px solid var(--ligne);border-radius:8px;padding:10px;margin:8px 0}
.note{font-size:12px;color:#6B5B4E;margin:6px 2px}.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11.5px;font-weight:600;color:#fff}
.b-green{background:var(--vert)}.b-red{background:var(--rouge)}.b-amber{background:var(--ambre);color:#3D2B1F}.b-blue{background:var(--bleu)}
.box{border-radius:8px;padding:10px 14px;margin:12px 0;border-left:5px solid}.box ul{margin:6px 0 2px 18px;padding:0}.box-list li{margin:3px 0}
.box-red{background:#FBEAEA;border-color:var(--rouge)}.box-amber{background:#FDF3DE;border-color:var(--ambre)}.box-blue{background:#EAF0F8;border-color:var(--bleu)}.box-green{background:#EAF3E3;border-color:var(--vert)}
footer{font-size:12px;color:#6B5B4E;border-top:1px solid var(--ligne);margin-top:30px;padding-top:12px}footer li{margin:2px 0}
@media print{nav{display:none}.tab{display:block!important;page-break-after:always}header{background:#fff;color:#000}}
"""

JS = """
const SPECS=%SPECS%;const COULEURS=%COULEURS%;const faits={};
function fmt(v){return (v===null||v===undefined)?'':Number(v).toLocaleString('fr-FR',{maximumFractionDigits:0})}
function build(id){
  if(faits[id]||typeof Chart==='undefined'){return}
  const s=SPECS[id],el=document.getElementById(id);if(!el)return;faits[id]=1;
  const horiz=!!s.horizontal,rond=s.type==='doughnut';
  const u=s.unite||'€';
  const opts={responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'},tooltip:{callbacks:{label:c=>{const v=rond?c.parsed:(horiz?c.parsed.x:c.parsed.y);return (c.dataset.label?c.dataset.label+' : ':'')+fmt(v)+' '+u}}}}};
  if(!rond){const xt={},yt={};if(horiz){xt.callback=v=>fmt(v)}else{yt.callback=v=>fmt(v)}
    opts.scales={x:{stacked:!!s.stacked,ticks:xt},y:{stacked:!!s.stacked,ticks:yt}};if(horiz)opts.indexAxis='y'}
  new Chart(el,{type:s.type==='doughnut'?'doughnut':s.type,data:{labels:s.labels,datasets:s.datasets},options:opts});
}
function show(i){
  document.querySelectorAll('.tab').forEach((t,k)=>t.classList.toggle('on',k===i));
  document.querySelectorAll('nav button').forEach((b,k)=>b.classList.toggle('on',k===i));
  document.querySelectorAll('#t'+i+' canvas').forEach(c=>build(c.id));
  try{history.replaceState(null,'','#'+i)}catch(e){}
}
if(typeof Chart==='undefined'){document.querySelectorAll('.chartbox').forEach(b=>{b.style.height='auto';b.innerHTML='<p class="note">Graphique indisponible (bibliothèque Chart.js non chargée : connexion internet requise). Les tableaux restent valables.</p>'})}
const dep=parseInt((location.hash||'#0').slice(1))||0;show(Math.min(dep,document.querySelectorAll('.tab').length-1));
"""


def assembler(cx, titre, sous_titre, onglets, notes):
    nav = "".join(f'<button onclick="show({i})" class="{"on" if i == 0 else ""}">{NUM[i] if i < len(NUM) else i + 1} {e(nom)}</button>'
                  for i, (nom, _) in enumerate(onglets))
    corps = "".join(f'<section class="tab" id="t{i}"><h2>{NUM[i] if i < len(NUM) else i + 1} {e(nom)}</h2>{contenu}</section>'
                    for i, (nom, contenu) in enumerate(onglets))
    specs = json.dumps(cx.R.charts, ensure_ascii=False).replace("</", "<\\/")
    js = JS.replace("%SPECS%", specs).replace("%COULEURS%", json.dumps(C))
    notes_html = "".join(f"<li>{n}</li>" for n in notes)
    return (f'<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(titre)}</title><style>{CSS}</style></head><body><header><h1>{e(titre)}</h1><p>{e(sous_titre)}</p><nav>{nav}</nav></header>'
            f'<main>{corps}<footer><strong>Conventions et limites</strong><ul>{notes_html}</ul></footer></main>'
            f'<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"></script><script>{js}</script></body></html>')


# --------------------------------------------------------------------------- point d'entree

ALIAS_TYPES = [
    ("sci_is", ("sci_is", "sci is", "sci à l'is", "sci a l'is", "sci a lis", "sci à l is", "sci-is", "sciis", "sci à l’is")),
    ("sci_ir", ("sci_ir", "sci ir", "sci à l'ir", "sci a l'ir", "sci-ir", "sciir", "sci à l’ir")),
    ("esms", ("esms", "ehpad", "ime", "esat", "mas", "fam", "chrs", "medico", "médico", "établissement social", "etablissement social")),
    ("association", ("association", "asso", "loi 1901", "1901", "club")),
    ("bnc", ("bnc", "libéral", "liberal", "libérale", "médecin", "medecin", "avocat", "kiné", "kine", "osteo", "ostéo", "infirmier", "infirmière", "2035")),
    ("bic", ("bic", "sas", "sarl", "eurl", "sasu", "ei", "commerce", "artisan", "garage", "société", "societe", "entreprise")),
]


def _contient(t, mot):
    """Mot court (acronyme) : reconnu seulement comme mot entier (evite « ime » dans « regime »)."""
    if len(mot) <= 4:
        return re.search(r"(?<![a-zà-ÿ0-9])" + re.escape(mot) + r"(?![a-zà-ÿ0-9])", t) is not None
    return mot in t


def normaliser_type(t):
    t = (t or "").strip().lower().replace("’", "'")
    if not t:
        return None
    for code, mots in ALIAS_TYPES:
        if t == code or any(_contient(t, m) for m in mots):
            return code
    return None


def suggestion_type(J):
    """Indication d'apres les comptes (a confirmer par l'utilisateur, jamais appliquee seule)."""
    c = set(J.net)
    has = lambda *p: any(x.startswith(p) for x in c)
    if has("73"):
        return "association ESMS (établissement social ou médico-social : comptes 73 de tarification)"
    if has("756") or (has("754") and has("74")):
        return "association loi 1901 (cotisations ou dons) ; ESMS si c'est un établissement social ou médico-social"
    if has("707", "607", "601", "602"):
        return "BIC (commerce, artisanat, société d'exploitation)"
    if has("164") and has("752", "706", "70") and has("213", "211", "212"):
        return "SCI (à l'IS si des comptes 681 ou 695 sont mouvementés, sinon à l'IR)"
    if has("646") and has("70"):
        return "BNC (profession libérale)"
    if has("70"):
        return "BNC (profession libérale) ou BIC de prestation de services"
    return None


def question_type(J=None):
    txt = ("Type de dossier non indiqué. Demande-le à l'utilisateur, ne devine pas. Valeurs possibles pour type_dossier : "
           + ", ".join(f"{k} = {v}" for k, v in TYPES.items()) + ". Pour une SCI, préciser IR ou IS.")
    if J is not None:
        s = suggestion_type(J)
        if s:
            txt += f" D'après les comptes du fichier, cela ressemble à : {s} (à faire confirmer)."
    return txt


def nom_fichier(nom, typ, fin):
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", (nom or "client")).strip("_")[:40] or "client"
    return f"TDB_{typ}_{base}_{fin:%Y-%m}.html"


def _txt(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def generer(chemin, type_dossier=None, chemin_n1=None, date_arrete=None, nom_client=None, valeur_bien=None,
            surface_m2=None, journees_realisees=None, journees_theoriques=None, dossier_sortie=None):
    import tdb_types
    lignes, illisibles = cf.lire_fec(chemin)
    arrete = cf.date_de(date_arrete) if date_arrete else None
    if date_arrete and not arrete:
        raise ValueError(f"date_arrete illisible : {date_arrete} (format attendu JJ/MM/AAAA)")
    J = Jeu(lignes, arrete)
    if J.vide:
        raise ValueError("aucune écriture datée dans la période demandée.")
    typ = normaliser_type(type_dossier)
    if typ is None:
        return question_type(J), None
    if not any(abs(sum(v)) > 0.005 or any(abs(x) > 0.005 for x in v) for c, v in J.net.items() if c[:1] in ("6", "7")):
        raise ValueError("aucun mouvement sur les classes 6 et 7 : ce FEC ressemble à un fichier après clôture (comptes de gestion soldés). "
                         "Fournir le FEC avant écritures de clôture, ou une extraction des écritures de l'exercice.")
    J1 = J1full = None
    notes_n1 = []
    if chemin_n1:
        l1, _ = cf.lire_fec(cf.resoudre_chemin(chemin_n1) if hasattr(cf, "resoudre_chemin") else chemin_n1)
        J1full = Jeu(l1)
        J1 = Jeu(l1, nb_mois=J.n)
        if J1.vide:
            raise ValueError("le FEC N-1 ne contient aucune écriture datée.")
        if J1.mois[0][1] != J.mois[0][1]:
            notes_n1.append(f"Attention : N-1 débute en {MOIS[J1.mois[0][1] - 1]} et N en {MOIS[J.mois[0][1] - 1]} ; les mois sont alignés par rang, pas par date.")
        if J1.incomplet:
            notes_n1.append(f"Le FEC N-1 ne couvre pas les {J.n} mois de N : les mois manquants sont à zéro, comparaison à interpréter avec prudence.")
    opts = {"valeur_bien": valeur_bien, "surface_m2": surface_m2, "journees_realisees": journees_realisees,
            "journees_theoriques": journees_theoriques}
    if J1full is not None:
        opts["rn_n1_annuel"] = (J1full.ser(("7",), -1) - J1full.ser(("6",), 1)).cum
    cx = Ctx(J, J1, typ, nom_client, opts)
    builder = getattr(tdb_types, "construire_" + typ)
    onglets, resume, notes = builder(cx)
    notes = notes + notes_n1
    periode = f"{J.debut:%d/%m/%Y} au {J.fin:%d/%m/%Y} ({J.n} mois)"
    titre = f"Tableau de bord — {nom_client or 'dossier'} — {TYPES[typ]}"
    sous = f"Période : {periode}" + (" · comparaison N-1 sur les mêmes mois" if J1 else " · sans comparaison N-1 (FEC N-1 non fourni)")
    page = assembler(cx, titre, sous, onglets, notes)
    dossier = dossier_sortie or os.path.join(ICI, "sorties")
    os.makedirs(dossier, exist_ok=True)
    sortie = os.path.join(dossier, nom_fichier(nom_client, typ, J.fin))
    with open(sortie, "w", encoding="utf-8") as f:
        f.write(page)
    lignes_txt = [f"Tableau de bord {TYPES[typ]} — période {periode}" + ("" if J1 else " — pas de N-1"),
                  *resume]
    if cx.vig:
        lignes_txt.append("Points de vigilance calculés :")
        ordre = {"red": 0, "amber": 1, "blue": 2}
        for niv, t in sorted(cx.vig, key=lambda x: ordre.get(x[0], 3))[:8]:
            lignes_txt.append(f"- {_txt(t)}")
    if illisibles:
        lignes_txt.append(f"({illisibles} ligne(s) du FEC illisible(s), ignorée(s).)")
    lignes_txt.append(f"Fichier complet (à ouvrir dans le navigateur) : {cf.vers_affichage(sortie)}")
    lignes_txt.append("Cite uniquement ces chiffres calculés par l'outil ; ne refais aucun calcul ; ne reclasse rien sans validation de l'utilisateur.")
    return "\n".join(lignes_txt), sortie


def anomalies_mensuelles(cx):
    """Mois dont le total des charges ou des produits est negatif ou tres au-dessus des autres (extournes, inventaires, provisions)."""
    for nom, ser in (("charges", cx.J.ser(("6",), 1)), ("produits", cx.J.ser(("7",), -1))):
        v = ser.v
        if cx.n < 3:
            continue
        for i, x in enumerate(v):
            if x < -1000:
                cx.vigil("amber", f"Total des {nom} négatif en {cx.labels[i]} ({fm(x)} €) : extourne, régularisation de stock ou de provisions probable ; la lecture mensuelle est à interpréter avec prudence.")
        autres = sorted(y for k, y in enumerate(v) if y > 0)
        if autres:
            med = autres[len(autres) // 2]
            for i, x in enumerate(v):
                if med > 0 and x > 3 * med and x - med > 5000:
                    cx.vigil("amber", f"Pic de {nom} en {cx.labels[i]} ({fm(x)} € contre {fm(med)} € en médiane) : écritures d'inventaire, de provisions ou de régularisation à vérifier.")
