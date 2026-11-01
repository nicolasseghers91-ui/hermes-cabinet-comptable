# -*- coding: utf-8 -*-
"""Construction des onglets du tableau de bord pour chaque type de dossier (voir tableau_bord.generer).

Chaque fonction construire_<type>(cx) renvoie (onglets, resume, notes) :
  onglets = [(nom, html)], resume = lignes de texte pour le modele, notes = conventions affichees en pied de page.
Tout est calcule ici en Python ; aucune valeur n'est estimee par le modele.
"""
import tableau_bord as tb
from tableau_bord import (C, Ser, ds, e, evol, evol_s, fm, pc, part, badge, var_cell, spec_bar, spec_line, spec_donut,
                          tableau_mensuel, tableau_evolution, synthese, onglet_tresorerie, scenarios, onglet_vigilance,
                          variations_vigilance, anomalies_comptes, calculs_bic, treso_bfr)

SEUIL_VARIATION = 100   # skill : variations N/N-1 superieures a +/-100 % signalees


# --------------------------------------------------------------------------- paires N / N-1

class P:
    """Une serie pour N et, si fourni, pour N-1 ; les operations s'appliquent aux deux."""

    def __init__(self, a, b=None):
        self.a, self.b = a, b

    def _o(self, o):
        if isinstance(o, P):
            return o
        return P(o, o if self.b is not None else None)

    def _op(self, o, f):
        o = self._o(o)
        return P(f(self.a, o.a), None if self.b is None or o.b is None else f(self.b, o.b))

    def __add__(self, o):
        return self._op(o, lambda x, y: x + y)

    __radd__ = __add__

    def __sub__(self, o):
        return self._op(o, lambda x, y: x - y)

    def __mul__(self, k):
        return P(self.a * k, None if self.b is None else self.b * k)

    def __neg__(self):
        return self * -1


def pser(cx, prefixes, sens=1, excl=()):
    return P(cx.J.ser(prefixes, sens, excl), cx.J1.ser(prefixes, sens, excl) if cx.J1 is not None else None)


def zero(cx):
    return P(Ser([0.0] * cx.n), Ser([0.0] * cx.n) if cx.J1 is not None else None)


def row(label, p, cls="", bon=True):
    return (label, p.a, p.b, cls, bon)


def mois_actifs(s):
    return sum(1 for x in s.v if abs(x) > 0.005)


# --------------------------------------------------------------------------- briques graphiques / tableaux

def lignes_par_compte(cx, prefixes, sens=1, excl=(), bon=True, total=None):
    out = []
    for c in cx.J.comptes(prefixes, excl):
        sN = cx.J.ser_compte(c, sens)
        s1 = cx.J1.ser_compte(c, sens) if cx.J1 is not None else None
        if not any(abs(x) > 0.005 for x in sN.v) and (s1 is None or not any(abs(x) > 0.005 for x in s1.v)):
            continue
        out.append((f"{c} {cx.J.lib.get(c, '')[:34]}", sN, s1, "", bon))
    if out and total:
        p = pser(cx, prefixes, sens, excl)
        out.append((total, p.a, p.b, "rt", bon))
    return out


def comptes_n1_seuls(cx, prefixes, excl=()):
    """Comptes presents en N-1 mais absents de N (ils comptent dans le total N-1)."""
    if cx.J1 is None:
        return []
    return [c for c in cx.J1.comptes(prefixes, excl) if c not in cx.J.net]


def barres_mensuelles(cx, titre, p, couleur=None, bon=True):
    liste = [ds("N", p.a.v, couleur or C["terra"])]
    if p.b is not None:
        liste.append(ds("N-1", p.b.v, "#B9AFA2"))
    return f"<h3>{e(titre)}</h3>" + cx.R.canvas(spec_bar(cx.labels, liste), 240)


def donut(cx, titre, groupes):
    """groupes : [(label, prefixes, sens, excl)] ; ne garde que les cumuls positifs."""
    lab, val = [], []
    for label, prefixes, sens, excl in groupes:
        v = cx.J.ser(prefixes, sens, excl).cum
        if v > 0.5:
            lab.append(label)
            val.append(round(v, 2))
    if not val:
        return ""
    return f"<h3>{e(titre)}</h3>" + cx.R.canvas(spec_donut(lab, val), 280)


def top_comptes(cx, titre, prefixes, sens=1, n=10, excl=()):
    cs = sorted(cx.J.comptes(prefixes, excl), key=lambda c: -abs(cx.J.ser_compte(c, sens).cum))[:n]
    cs = [c for c in cs if abs(cx.J.ser_compte(c, sens).cum) > 0.5]
    if not cs:
        return ""
    labels = [f"{c} {cx.J.lib.get(c, '')[:26]}" for c in cs]
    liste = [ds("N", [cx.J.ser_compte(c, sens).cum for c in cs], C["terra"])]
    if cx.J1 is not None:
        liste.append(ds("N-1", [cx.J1.ser_compte(c, sens).cum for c in cs], "#B9AFA2"))
    return f"<h3>{e(titre)}</h3>" + cx.R.canvas(spec_bar(labels, liste, horizontal=True), max(220, 36 * len(cs) + 60))


def table_postes(cx, titre, postes, base, base_label, bon_defaut=True):
    """Tableau cumul de postes [(label, P, bon)] avec % de la base et N-1."""
    rows = []
    for label, p, bon in postes:
        if abs(p.a.cum) < 0.005 and (p.b is None or abs(p.b.cum) < 0.005):
            continue
        cells = [e(label), fm(p.a.v[-1]), fm(p.a.cum), tb.pc(part(p.a.cum, base))]
        if cx.R.has_n1:
            c1 = p.b.cum if p.b is not None else None
            cells += [fm(c1), var_cell(p.a.cum, c1, bon)]
        rows.append(("", cells))
    return f"<h3>{e(titre)}</h3>" + cx.R.table(tb.entetes_cumul(cx, base_label), rows)


def cartes_kpi(items):
    return items


def eur_k(x):
    return fm(x) + " €"


def pied_notes(extra=()):
    base = [
        "Résultat net = total classe 7 − total classe 6, tel qu'il ressort du FEC (écritures de clôture ignorées). Aucun reclassement n'est appliqué automatiquement.",
        "Variations : « n.s. » quand la référence N-1 est nulle ; toutes les valeurs sont en euros, soldes nets des comptes.",
        "Tous les chiffres sont calculés par programme à partir du FEC ; le fichier ne quitte pas le poste.",
    ]
    return list(extra) + base


# --------------------------------------------------------------------------- BIC

def construire_bic(cx):
    J, J1 = cx.J, cx.J1
    k = calculs_bic(J)
    k1 = calculs_bic(J1) if J1 is not None else None

    def kp(nom):
        return P(k[nom], k1[nom] if k1 else None)

    ca, conso, marge, ext, va = kp("ca"), kp("conso"), kp("marge"), kp("ext"), kp("va")
    sub, pers, imp, ebe, dot = kp("sub"), kp("pers"), kp("impots"), kp("ebe"), kp("dot")
    prod_st = kp("prod_st")
    ca_hors_706 = pser(cx, ("701", "702", "703", "704", "705"), -1)
    autres_ch, autres_pr, rex, fin, exc, is_, rn = kp("autres_ch"), kp("autres_pr"), kp("rex"), kp("fin"), kp("exc"), kp("is"), kp("rn")
    c7, c6 = kp("c7"), kp("c6")
    base = ca.a.cum
    i = cx.n - 1
    t = treso_bfr(J)
    t1 = treso_bfr(J1) if J1 is not None else None
    resume = [
        f"CA (comptes 70) cumul : {fm(ca.a.cum)} €" + (f" (N-1 : {fm(ca.b.cum)} €, {pc(evol(ca.a.cum, ca.b.cum))})" if ca.b is not None and ca.b.cum else ""),
        *([f"Dont ventes de production (701 à 705) : {fm(ca_hors_706.a.cum)} € (hors convention 706-708 : à confirmer avec le dossier)."] if abs(ca_hors_706.a.cum) > 0.5 else []),
        f"Marge brute : {fm(marge.a.cum)} € ({pc(part(marge.a.cum, base))} du CA) · Valeur ajoutée : {fm(va.a.cum)} € ({pc(part(va.a.cum, base))})",
        f"EBE : {fm(ebe.a.cum)} € ({pc(part(ebe.a.cum, base))} du CA)" + (f" (N-1 : {fm(ebe.b.cum)} €)" if ebe.b is not None else ""),
        f"Résultat net (classe 7 − classe 6) : {fm(rn.a.cum)} € ({pc(part(rn.a.cum, base))} du CA)" + (f" (N-1 : {fm(rn.b.cum)} €)" if rn.b is not None else ""),
        f"Trésorerie fin de période : {fm(t['treso'].v[i])} € · BFR : {fm(t['bfr'].v[i])} €",
    ]
    if abs(k["ecart_controle"]) > 0.5:
        cx.vigil("red", f"Contrôle interne : la cascade SIG s'écarte de classe 7 − classe 6 de {fm(k['ecart_controle'])} € (à investiguer).")

    # 1 Synthèse
    cartes = [
        ("CA cumul", fm(ca.a.cum) + " €", f"Dernier mois {fm(ca.a.v[i])} €" + (f" · N-1 {badge(evol_s(ca.a.cum, ca.b.cum), True)}" if ca.b is not None else ""), "card-m"),
        ("Marge brute", pc(part(marge.a.cum, base)), f"{fm(marge.a.cum)} €" + (f" · N-1 {pc(part(marge.b.cum, ca.b.cum))}" if ca.b is not None else ""), ""),
        ("EBE", fm(ebe.a.cum) + " €", f"{pc(part(ebe.a.cum, base))} du CA" + (f" · N-1 {fm(ebe.b.cum)} €" if ebe.b is not None else ""), ""),
        ("Résultat net", fm(rn.a.cum) + " €", f"{pc(part(rn.a.cum, base))} du CA" + (f" · N-1 {fm(rn.b.cum)} €" if rn.b is not None else ""), "card-m"),
        ("Trésorerie", fm(t["treso"].v[i]) + " €", f"fin {cx.labels[i]}", ""),
    ]
    rows = [("Chiffre d'affaires (70)", ca.a, ca.b, True, ""), ("Marge brute", marge.a, marge.b, True, ""),
            ("Excédent brut d'exploitation", ebe.a, ebe.b, True, ""), ("Total produits (classe 7)", c7.a, c7.b, True, ""),
            ("Total charges (classe 6)", c6.a, c6.b, False, ""), ("Résultat net", rn.a, rn.b, True, "rt")]
    h1 = synthese(cx, cartes, rows, [("CA", ca.a, C["terra"]), ("Charges", c6.a, C["ocre"]), ("Résultat net", rn.a, C["vert"])])

    # 2 Tableau cumul mensuel
    lignes = [row("Chiffre d'affaires (70)", ca, "rt"),
              row("Autres produits (hors CA)", c7 - ca),
              row("Total produits", c7, "rt"),
              row("Achats et consommations (60 hors 606)", conso, "", False),
              row("Charges externes (606, 61, 62)", ext, "", False),
              row("Impôts et taxes (63)", imp, "", False),
              row("Charges de personnel (64)", pers, "", False),
              row("Autres charges de gestion (65)", autres_ch, "", False),
              row("Dotations (68)", dot, "", False),
              row("Charges financières et exceptionnelles (66, 67)", pser(cx, ("66", "67")), "", False),
              row("Impôt sur les bénéfices (69)", is_, "", False),
              row("Total charges", c6, "rt", False),
              row("Résultat net", rn, "rh")]
    h2 = tableau_mensuel(cx, lignes, base, "% CA")

    # 3 Produits
    prod = lignes_par_compte(cx, ("7",), -1, total="Total produits")
    h3 = tableau_mensuel(cx, prod, base, "% CA") if prod else "<p>Aucun produit.</p>"
    h3 += donut(cx, "Répartition du CA", [("701-705 Production vendue", ("701", "702", "703", "704", "705"), -1, ()), ("706 Prestations de services", ("706",), -1, ()),
                                         ("707 Ventes de marchandises", ("707",), -1, ()), ("708 Activités annexes", ("708",), -1, ())])
    h3 += barres_mensuelles(cx, "CA mensuel (70), N et N-1", ca)

    # 4 Charges
    cat = [("Achats et consommations (60)", pser(cx, ("60",), 1, ("606",)), False), ("Charges externes (606, 61, 62)", ext, False),
           ("Impôts et taxes (63)", imp, False), ("Personnel (64)", pers, False), ("Autres charges de gestion (65)", autres_ch, False),
           ("Charges financières (66)", pser(cx, ("66",)), False), ("Charges exceptionnelles (67)", pser(cx, ("67",)), False),
           ("Dotations (68)", dot, False), ("Impôt sur les bénéfices (69)", is_, False), ("Total charges", c6, False)]
    h4 = table_postes(cx, "Charges par nature", cat, base, "% CA")
    h4 += donut(cx, "Répartition des charges", [(l, p_, 1, ()) for l, p_ in (
        ("Achats et consommations", ("60",)), ("Services extérieurs (61, 62)", ("61", "62")), ("Impôts et taxes", ("63",)),
        ("Personnel", ("64",)), ("Autres (65-69)", ("65", "66", "67", "68", "69")))])
    h4 += barres_mensuelles(cx, "Total charges mensuel, N et N-1", c6, C["ocre"])

    # 5 Charges externes (détail)
    h5 = tableau_mensuel(cx, lignes_par_compte(cx, ("60", "61", "62"), 1, bon=False, total="Total 60, 61, 62"), base, "% CA") if J.comptes(("60", "61", "62")) else ""
    h5 += top_comptes(cx, "Dix premiers comptes d'achats et charges externes (cumul)", ("60", "61", "62"))

    # 6 SIG
    sig = [row("Chiffre d'affaires (70)", ca, "rt")]
    if abs(prod_st.a.cum) > 0.5 or (prod_st.b is not None and abs(prod_st.b.cum) > 0.5):
        sig.append(row("+ Production stockée et immobilisée (71, 72)", prod_st))
    sig += [row("− Consommations (60 hors 606)", -conso, ""),
           row("= MARGE BRUTE", marge, "rh"),
           row("− Charges externes (606, 61, 62)", -ext),
           row("= VALEUR AJOUTÉE", va, "rh"),
           row("+ Subventions d'exploitation (74)", sub),
           row("− Impôts et taxes (63)", -imp), row("− Charges de personnel (64)", -pers),
           row("= EXCÉDENT BRUT D'EXPLOITATION", ebe, "rh"),
           row("− Dotations (68)", -dot), row("− Autres charges de gestion (65)", -autres_ch),
           row("+ Autres produits d'exploitation (71, 72, 75, 78, 79)", autres_pr),
           row("= RÉSULTAT D'EXPLOITATION", rex, "rh"),
           row("± Résultat financier (76 − 66)", fin), row("± Résultat exceptionnel (77 − 67)", exc),
           row("− Impôt sur les bénéfices (69)", -is_),
           row("= RÉSULTAT NET", rn, "rh")]
    h6 = "<h3>Valeurs</h3>" + tableau_mensuel(cx, sig, base, "% CA")
    ent = ["Poste (% du CA)"] + cx.labels + ["Cumul"]
    rows_p = [(cl, [e(l)] + [tb.pc(part(x, c)) if c else "—" for x, c in zip(a.v, ca.a.v)] + [tb.pc(part(a.cum, base))]) for l, a, _, cl, b in sig]
    h6 += "<h3>En % du CA</h3>" + cx.R.table(ent, rows_p,
          "Subventions d'exploitation (74) placées entre la valeur ajoutée et l'EBE (méthode PCG). Contrôle : résultat net = classe 7 − classe 6 (écart "
          f"{fm(k['ecart_controle'])} €).")

    # 7 Marges par famille (hors variation de stock)
    prod_v = pser(cx, ("701", "702", "703", "704", "705"), -1)
    has_prod = abs(prod_v.a.cum) > 0.5 or (prod_v.b is not None and abs(prod_v.b.cum) > 0.5)
    march_v = pser(cx, ("707",), -1)
    prest_v = pser(cx, ("706", "708"), -1)
    ach607, ach_mat, sous = pser(cx, ("607",)), pser(cx, ("601", "602")), pser(cx, ("604", "605", "611"))
    var_march, var_mat = pser(cx, ("6037",)), pser(cx, ("6031", "6032"))
    pst_prod = pser(cx, ("71",), -1)
    z = zero(cx)
    familles = [
        {"nom": "Ventes de marchandises (707)", "v": march_v, "a": ach607 + (z if has_prod else ach_mat), "var": var_march + (z if has_prod else var_mat), "ps": z,
         "ach_txt": "607" + ("" if has_prod else " + 601 + 602"), "stk": ("37",) if has_prod else ("31", "32", "37")},
        {"nom": "Production vendue (701 à 705)", "v": prod_v, "a": ach_mat, "var": var_mat, "ps": pst_prod, "ach_txt": "601 + 602 (matières et emballages, hors main-d'œuvre)", "stk": ("31", "32")},
        {"nom": "Prestations et services (706 + 708)", "v": prest_v, "a": sous, "var": z, "ps": z, "ach_txt": "604 + 605 + 611", "stk": ()},
    ]
    familles = [f for f in familles if abs(f["v"].a.cum) > 0.5 or (f["v"].b is not None and abs(f["v"].b.cum) > 0.5)]
    rows_f = []
    for f in familles:
        marg = f["v"] - f["a"]
        f["marge"] = marg
        t_a = part(marg.a.cum, f["v"].a.cum)
        t_b = part(marg.b.cum, f["v"].b.cum) if marg.b is not None else None
        cells = [e(f["nom"]), fm(f["v"].a.cum), fm(f["a"].a.cum) + f' <span class="note">({f["ach_txt"]})</span>', fm(marg.a.cum), tb.pc(t_a)]
        if cx.R.has_n1:
            dpt = round((t_a or 0) - (t_b or 0), 1) if t_a is not None and t_b is not None else None
            cells += [tb.pc(t_b), "—" if dpt is None else f'<span class="badge b-blue">{"+" if dpt > 0 else ("−" if dpt < 0 else "")}{fm(abs(dpt), 1)} pt</span>']
        rows_f.append(("", cells))
    ent_f = ["Famille", "Ventes", "Achats rattachés", "Marge hors stock", "Taux de marge"] + (["Taux N-1", "Écart"] if cx.R.has_n1 else [])
    if rows_f:
        h7 = "<h3>Marge par famille d'activité (cumul, hors variation de stock)</h3>" + cx.R.table(
            ent_f, rows_f, "Rattachement des achats aux familles = convention de lecture à valider selon le dossier. Les variations de stock (603, 71) sont isolées dans l'onglet « Marge hors stock ».")
        ds_t = []
        for f, col in zip(familles, (C["terra"], C["ocre"], C["vert"])):
            taux = Ser([part(m_, v_) or 0.0 for m_, v_ in zip(f["marge"].a.v, f["v"].a.v)])
            ds_t.append(dict(ds("Taux de marge — " + f["nom"], taux.v, col), fill=False, tension=0.25))
        h7 += "<h3>Taux de marge mensuel (%)</h3>" + cx.R.canvas(spec_line(cx.labels, ds_t, unite="%"), 240)
    else:
        h7 = "<p>Aucune vente de marchandises, de production ou de prestations identifiable (comptes 701 à 708).</p>"
    onglets = [("Synthèse", h1), ("Tableau cumul", h2), ("Produits", h3), ("Charges", h4), ("Charges externes", h5), ("SIG", h6), ("Marges", h7)]

    # 7bis Marge hors variation de stock : des qu'un compte de variation de stock (603, 71) est mouvemente
    stock_mvt = [f for f in familles if any(abs(x) > 0.5 for x in (f["var"].a.v + f["ps"].a.v))]
    if stock_mvt:
        hs, rows_h = "", []
        notes_stock = []
        for f in stock_mvt:
            effet = f["ps"] - f["var"]                     # + : stock en hausse (marge affichee gonflee)
            avec = f["marge"] + effet
            v_a = f["v"].a.cum
            rows_h.append(("", [e(f["nom"]), fm(v_a), fm(f["marge"].a.cum), tb.pc(part(f["marge"].a.cum, v_a)), fm(effet.a.cum),
                                fm(part(effet.a.cum, v_a) or 0, 1) + " pt", fm(avec.a.cum), tb.pc(part(avec.a.cum, v_a))]))
            if f["stk"]:
                var_phys = J.ser(f["stk"], 1).cum - J.ouverture(f["stk"]) + (J.ser(("33", "34", "35", "36"), 1).cum - J.ouverture(("33", "34", "35", "36")) if f["ps"].a.cum else 0)
                sens = "constitution de stock" if effet.a.cum > 0 else ("déstockage" if effet.a.cum < 0 else "pas d'effet")
                ok = abs(var_phys) < 1 or abs(effet.a.cum) < 1 or (effet.a.cum > 0) == (var_phys > 0)
                notes_stock.append(f"{f['nom']} : effet des variations de stock {fm(effet.a.cum)} € ({sens}) ; variation constatée des comptes de stock 3x hors à-nouveaux : {fm(var_phys)} € — "
                                   + ("les deux sens concordent." if ok else "les deux sens ne concordent pas : à vérifier (inventaire non encore passé, stock partiel…)."))
        hs += "<h3>Réconciliation marge hors stock / marge avec variation de stock (cumul)</h3>" + cx.R.table(
            ["Famille", "Ventes", "Marge hors stock", "Taux", "Effet des variations de stock", "En points de marge", "Marge avec stock", "Taux"], rows_h,
            "Effet de stock = production stockée (71) − variation de stock des approvisionnements et marchandises (603). Positif : le stock augmente et la marge affichée est gonflée ; négatif : déstockage.")
        hs += cx.R.box("blue", "Contrôle de cohérence avec les stocks", notes_stock + ["Les variations de stock sont le plus souvent constatées en fin de période ou à l'inventaire : un mois sans écriture n'est pas anormal."])
        ds_t = []
        for f, col in zip(stock_mvt, (C["terra"], C["ocre"], C["vert"])):
            taux = Ser([part(m_, v_) or 0.0 for m_, v_ in zip(f["marge"].a.v, f["v"].a.v)])
            ds_t.append(dict(ds("Hors stock — " + f["nom"], taux.v, col), fill=False, tension=0.25))
        hs += "<h3>Taux de marge hors stock par mois (%)</h3>" + cx.R.canvas(spec_line(cx.labels, ds_t, unite="%"), 220)
        onglets.append(("Marge hors stock", hs))
        for f in stock_mvt:
            effet = f["ps"] - f["var"]
            avec = f["marge"] + effet
            resume.append(f"{f['nom']} : marge hors stock {pc(part(f['marge'].a.cum, f['v'].a.cum))} ({fm(f['marge'].a.cum)} €) contre {pc(part(avec.a.cum, f['v'].a.cum))} avec variations de stock (effet {fm(effet.a.cum)} €).")

    # 8 Trésorerie & BFR
    onglets.append(("Trésorerie & BFR", onglet_tresorerie(cx, t, t1, base / cx.n)))

    # 9 Scénarios
    variables = pser(cx, ("60", "611"))
    var_hs = pser(cx, ("60", "611"), excl=("603",))     # hors variations de stock (6031, 6032, 6037...)
    s603, s71 = variables - var_hs, pst_prod
    fixes = c6 - variables - is_
    autres_hs = c7 - ca - s71
    stock = s71 - s603                                  # > 0 : stock en hausse (resultat gonfle)
    hsc, res = scenarios(cx, ca.a, var_hs.a, fixes.a, autres_hs.a, titre_ca="CA", stock=stock.a)
    onglets.append(("Scénarios", hsc))
    if abs(stock.a.cum) > 0.5:
        resume.append(f"Projection annuelle du résultat avant IS hors variation de stock (extrapolation linéaire) : bas {fm(res['Bas'][2])} €, central {fm(res['Central'][2])} €, haut {fm(res['Haut'][2])} € ; "
                      f"l'effet de stock constaté à ce jour ({fm(stock.a.cum)} €) n'est pas extrapolé (central avec cet effet : {fm(res['Central'][3])} €).")
    else:
        resume.append(f"Projection annuelle du résultat avant IS (extrapolation linéaire) : bas {fm(res['Bas'][2])} €, central {fm(res['Central'][2])} €, haut {fm(res['Haut'][2])} €.")

    # Vigilance
    if rn.a.cum < 0:
        cx.vigil("red", f"Résultat net négatif sur la période : {fm(rn.a.cum)} €.")
    if ebe.a.cum < 0:
        cx.vigil("red", f"EBE négatif sur la période : {fm(ebe.a.cum)} €.")
    if ebe.b is not None and ebe.b.cum > 0 and evol(ebe.a.cum, ebe.b.cum) is not None and evol(ebe.a.cum, ebe.b.cum) <= -30:
        cx.vigil("red", f"EBE en forte baisse : {pc(evol(ebe.a.cum, ebe.b.cum), 0)} par rapport à N-1 ({fm(ebe.b.cum)} € → {fm(ebe.a.cum)} €).")
    variations_vigilance(cx, [("Chiffre d'affaires", ca.a, ca.b, True), ("Achats et consommations", conso.a, conso.b, False), ("Charges externes", ext.a, ext.b, False),
                              ("Charges de personnel", pers.a, pers.b, False), ("Impôts et taxes", imp.a, imp.b, False), ("Dotations", dot.a, dot.b, False)],
                         SEUIL_VARIATION)
    s627 = J.ser(("627",), 1).cum
    if s627 > max(500, 0.01 * base):
        cx.vigil("amber", f"Compte 627 (services bancaires) : {fm(s627)} € ({pc(part(s627, base))} du CA), montant élevé : vérifier qu'aucun virement interne entre banques n'est imputé en charge. "
                          "Reclassement vers 512 possible mais NON appliqué : à valider avec vous.")
    if t["treso"].v[i] < 0:
        cx.vigil("red", f"Trésorerie négative en fin de période : {fm(t['treso'].v[i])} €.")
    else:
        charges_mens = (c6.a.cum - dot.a.cum) / cx.n
        if charges_mens > 0 and t["treso"].v[i] < charges_mens:
            cx.vigil("amber", f"Trésorerie ({fm(t['treso'].v[i])} €) inférieure à un mois de charges décaissables ({fm(charges_mens)} €).")
    if base > 0 and t["clients"].v[i] / (base / cx.n) * 30 > 60:
        cx.vigil("amber", f"Créances clients élevées : environ {fm(t['clients'].v[i] / (base / cx.n) * 30)} jours de CA (indicatif, TTC/HT non retraités).")
    if base <= 0:
        cx.vigil("red", "Aucun chiffre d'affaires (comptes 70) sur la période : vérifier la nature du dossier (holding ? association ? SCI ?).")
    if cx.J1 is None:
        cx.vigil("blue", "Pas de FEC N-1 : variations N/N-1 non calculées.")
    anomalies_comptes(cx)
    onglets.append(("Points de vigilance", onglet_vigilance(cx)))
    notes = pied_notes(["CA = comptes 70 (701 à 708, nets des rabais 709) : identique à la convention 706 + 707 + 708 tant que 701 à 705 ne sont pas utilisés. Tous les % « du CA » sont calculés sur ce CA et non sur le total des produits.",
                        "Scénarios : charges variables = comptes 60 et 611 (hors variations de stock 603) ; toutes les autres charges (hors IS) sont traitées comme fixes ; les variations de stock (71, 603) ne sont pas extrapolées ; résultat avant impôt sur les bénéfices."])
    return onglets, resume, notes


# --------------------------------------------------------------------------- utilitaires communs aux autres types

def postes_avec_reste(cx, groupes, total):
    """groupes : [(label, prefixes, sens, excl, bon)] ; ajoute « Autres » = total - somme des postes (tout est classe)."""
    postes, somme = [], zero(cx)
    for label, prefixes, sens, excl, bon in groupes:
        p = pser(cx, prefixes, sens, excl)
        postes.append((label, p, bon))
        somme = somme + p
    reste = total - somme
    if abs(reste.a.cum) > 0.5 or any(abs(x) > 0.5 for x in reste.a.v):
        postes.append(("Autres", reste, groupes[0][4] if groupes else True))
    return postes


def tresorerie_et_alertes(cx, t, charges_mens, libelle="la trésorerie"):
    i = cx.n - 1
    if t["treso"].v[i] < 0:
        cx.vigil("red", f"Trésorerie négative en fin de période : {fm(t['treso'].v[i])} €.")
    elif charges_mens > 0 and t["treso"].v[i] < charges_mens:
        cx.vigil("amber", f"Trésorerie ({fm(t['treso'].v[i])} €) inférieure à un mois de charges décaissables ({fm(charges_mens)} €).")


def tab_postes(cx, postes_defs, base, base_label, total_label, total, bon=False):
    """Tableau mensuel des postes + total, a partir de postes_avec_reste()."""
    lignes = [(l, p.a, p.b, "", b) for l, p, b in postes_defs if abs(p.a.cum) > 0.005 or any(abs(x) > 0.005 for x in p.a.v)]
    lignes.append((total_label, total.a, total.b, "rt", bon))
    return tableau_mensuel(cx, lignes, base, base_label)


# --------------------------------------------------------------------------- BNC

def construire_bnc(cx):
    J, J1 = cx.J, cx.J1
    i = cx.n - 1
    rec = pser(cx, ("70",), -1)
    c7, c6 = pser(cx, ("7",), -1), pser(cx, ("6",))
    autres_pr = c7 - rec
    res = c7 - c6
    base = rec.a.cum
    retro = pser(cx, ("622",))
    cotis = pser(cx, ("646",))
    pers = pser(cx, ("64",), 1, ("646",))
    loyer = pser(cx, ("613", "614"))
    t = {"treso": J.ser(("512", "514", "53", "519", "511"), 1).run()}
    cli, four = J.ser(("411", "413", "416", "418", "491"), 1).run(), J.ser(("401", "403", "408"), -1).run()
    avec_creances = any(abs(x) > 0.5 for x in list(cli.v) + list(four.v))
    t1 = None
    if J1 is not None:
        t1 = {"treso": J1.ser(("512", "514", "53", "519", "511"), 1).run(),
              "clients": J1.ser(("411", "413", "416", "418", "491"), 1).run(), "fournisseurs": J1.ser(("401", "403", "408"), -1).run()}
    t["clients"], t["fournisseurs"] = cli, four
    t["bfr"] = cli - four
    if t1:
        t1["bfr"] = t1["clients"] - t1["fournisseurs"]
    taux_ch = part(c6.a.cum, base)
    resume = [
        f"Recettes (comptes 70) cumul : {fm(rec.a.cum)} €" + (f" (N-1 : {fm(rec.b.cum)} €, {pc(evol(rec.a.cum, rec.b.cum))})" if rec.b is not None and rec.b.cum else ""),
        f"Dépenses professionnelles (classe 6) : {fm(c6.a.cum)} € · taux de charges : {pc(taux_ch)}",
        f"Résultat (bénéfice) : {fm(res.a.cum)} €" + (f" (N-1 : {fm(res.b.cum)} €)" if res.b is not None else ""),
        f"Rétrocessions/honoraires versés (622) : {fm(retro.a.cum)} € ({pc(part(retro.a.cum, base))} des recettes) · cotisations de l'exploitant (646) : {fm(cotis.a.cum)} €"
        + (f" ({pc(part(cotis.a.cum, res.a.cum))} du résultat)" if res.a.cum > 0 else ""),
        f"Trésorerie fin de période : {fm(t['treso'].v[i])} €",
    ]
    cartes = [("Recettes", fm(rec.a.cum) + " €", f"Dernier mois {fm(rec.a.v[i])} €" + (f" · N-1 {badge(evol_s(rec.a.cum, rec.b.cum), True)}" if rec.b is not None else ""), "card-m"),
              ("Dépenses", fm(c6.a.cum) + " €", f"Taux de charges {pc(taux_ch)}", ""),
              ("Résultat (bénéfice)", fm(res.a.cum) + " €", f"{pc(part(res.a.cum, base))} des recettes" + (f" · N-1 {fm(res.b.cum)} €" if res.b is not None else ""), "card-m"),
              ("Trésorerie", fm(t["treso"].v[i]) + " €", f"fin {cx.labels[i]}", "")]
    rows = [("Recettes (70)", rec.a, rec.b, True, ""), ("Dépenses (classe 6)", c6.a, c6.b, False, ""), ("Résultat", res.a, res.b, True, "rt")]
    h1 = synthese(cx, cartes, rows, [("Recettes", rec.a, C["terra"]), ("Dépenses", c6.a, C["ocre"]), ("Résultat", res.a, C["vert"])])
    h2 = tableau_mensuel(cx, [row("Recettes (70)", rec, "rt"), row("Autres produits (hors 70)", autres_pr), row("Total produits", c7, "rt"),
                              row("Rétrocessions et honoraires (622)", retro, "", False), row("Personnel salarié (64 hors 646)", pers, "", False),
                              row("Cotisations sociales de l'exploitant (646)", cotis, "", False), row("Loyers et charges (613, 614)", loyer, "", False),
                              row("Total dépenses (classe 6)", c6, "rt", False), row("Résultat", res, "rh")], base, "% recettes")
    prod = lignes_par_compte(cx, ("7",), -1, total="Total produits")
    h3 = tableau_mensuel(cx, prod, base, "% recettes") + barres_mensuelles(cx, "Recettes mensuelles (70), N et N-1", rec)
    groupes = [("Rétrocessions et honoraires versés (622)", ("622",), 1, (), False), ("Loyers et charges locatives (613, 614)", ("613", "614"), 1, (), False),
               ("Personnel salarié (64 hors 646)", ("64",), 1, ("646",), False), ("Cotisations de l'exploitant (646)", ("646",), 1, (), False),
               ("Impôts et taxes (63)", ("63",), 1, (), False), ("Fournitures, matériel, entretien (60, 615)", ("60", "615"), 1, (), False),
               ("Déplacements, réceptions (625)", ("625",), 1, (), False), ("Assurances (616)", ("616",), 1, (), False),
               ("Frais bancaires et divers (627, 618, 626, 628)", ("627", "618", "626", "628"), 1, (), False),
               ("Dotations (68)", ("68",), 1, (), False), ("Charges financières et exceptionnelles (66, 67)", ("66", "67"), 1, (), False)]
    pd = postes_avec_reste(cx, groupes, c6)
    h4 = tab_postes(cx, pd, base, "% recettes", "Total dépenses", c6)
    h4 += donut(cx, "Répartition des dépenses", [(l, pr, 1, ex) for l, pr, s_, ex, b in groupes])
    h4 += top_comptes(cx, "Dix premiers comptes de dépenses (cumul)", ("6",))
    h4 += barres_mensuelles(cx, "Dépenses mensuelles, N et N-1", c6, C["ocre"])
    dep_hors_retro = c6 - retro
    rec_nettes = rec - retro
    res_rows = [row("Recettes brutes (70)", rec, "rt"), row("− Rétrocessions d'honoraires (622)", -retro, ""), row("= Recettes nettes", rec_nettes, "rh"),
                row("+ Autres produits (hors 70)", autres_pr), row("− Autres dépenses professionnelles", -dep_hors_retro, ""), row("= RÉSULTAT (bénéfice imposable avant retraitements)", res, "rh")]
    h5 = tableau_mensuel(cx, res_rows, base, "% recettes")
    ind = [("Taux de charges (dépenses / recettes)", part(c6.a.cum, base), part(c6.b.cum, rec.b.cum) if c6.b is not None and rec.b is not None and rec.b.cum else None),
           ("Rétrocessions / recettes", part(retro.a.cum, base), part(retro.b.cum, rec.b.cum) if retro.b is not None and rec.b is not None and rec.b.cum else None),
           ("Cotisations de l'exploitant / résultat", part(cotis.a.cum, res.a.cum) if res.a.cum > 0 else None, part(cotis.b.cum, res.b.cum) if cotis.b is not None and res.b is not None and res.b.cum > 0 else None),
           ("Résultat / recettes", part(res.a.cum, base), part(res.b.cum, rec.b.cum) if res.b is not None and rec.b is not None and rec.b.cum else None)]
    h5 += "<h3>Indicateurs clés</h3>" + cx.R.table(["Indicateur", "N"] + (["N-1"] if cx.R.has_n1 else []),
          [("", [e(l), tb.pc(a)] + ([tb.pc(b)] if cx.R.has_n1 else [])) for l, a, b in ind],
          "Le résultat est le résultat comptable du FEC ; le bénéfice imposable (2035) suppose des retraitements fiscaux non effectués ici.")
    pe = [(l, p, b) for l, p, b in pd]
    h6 = "<h3>Dépenses en % des recettes (cumul)</h3>" + cx.R.canvas(spec_bar([l for l, p, b in pe if abs(p.a.cum) > 0.5],
          [ds("N", [round(part(p.a.cum, base) or 0, 2) for l, p, b in pe if abs(p.a.cum) > 0.5], C["terra"])] + (
          [ds("N-1", [round(part(p.b.cum, rec.b.cum) or 0, 2) if p.b is not None and rec.b is not None and rec.b.cum else 0 for l, p, b in pe if abs(p.a.cum) > 0.5], "#B9AFA2")] if cx.R.has_n1 else []),
          horizontal=True, unite="%"), 340)
    h6 += table_postes(cx, "Détail", [(l, p, b) for l, p, b in pe] + [("Résultat", res, True)], base, "% recettes")
    # trésorerie
    extra, postes = "", None
    if avec_creances:
        postes = [("Créances clients (411-418)", "clients", True), ("Dettes fournisseurs (401-408)", "fournisseurs", False)]
        extra = cx.R.box("blue", "Encaissements vs facturation", [
            "Des créances clients ou dettes fournisseurs sont comptabilisées : comptabilité d'engagement (BNC créances-dettes). "
            f"Créances clients fin de période : {fm(cli.v[i])} € ; l'écart entre recettes comptabilisées et encaissements correspond à la variation de ces créances."])
    onglets = [("Synthèse", h1), ("Tableau cumul", h2), ("Recettes", h3), ("Dépenses", h4), ("Résultat BNC", h5), ("Structure du résultat", h6)]
    tt = dict(t)
    if not avec_creances:
        tt.pop("bfr")
    onglets.append(("Trésorerie", onglet_tresorerie(cx, tt, t1, base / cx.n, libelle_bfr="Créances − dettes", extra=extra, postes=postes, delai=False)))
    variables = pser(cx, ("622", "60"))
    fixes = c6 - variables
    hsc, sc = scenarios(cx, rec.a, variables.a, fixes.a, autres_pr.a, titre_ca="Recettes")
    onglets.append(("Scénarios", hsc))
    resume.append(f"Projection annuelle du résultat (extrapolation linéaire) : bas {fm(sc['Bas'][2])} €, central {fm(sc['Central'][2])} €, haut {fm(sc['Haut'][2])} €.")
    if res.a.cum < 0:
        cx.vigil("red", f"Résultat négatif sur la période : {fm(res.a.cum)} €.")
    if rec.b is not None and rec.b.cum > 0 and evol(rec.a.cum, rec.b.cum) is not None and evol(rec.a.cum, rec.b.cum) <= -20:
        cx.vigil("red", f"Recettes en baisse de {pc(evol(rec.a.cum, rec.b.cum), 0)} par rapport à N-1.")
    variations_vigilance(cx, [("Recettes", rec.a, rec.b, True), ("Rétrocessions (622)", retro.a, retro.b, False), ("Personnel salarié", pers.a, pers.b, False),
                              ("Cotisations de l'exploitant (646)", cotis.a, cotis.b, False), ("Total dépenses", c6.a, c6.b, False)], SEUIL_VARIATION)
    if cotis.a.cum == 0 and base > 0 and cx.n >= 3:
        cx.vigil("blue", "Aucune cotisation sociale de l'exploitant (646) comptabilisée : normal si elles sont prélevées sur le compte de l'exploitant (compte 108), à vérifier selon la tenue du dossier.")
    tresorerie_et_alertes(cx, t, (c6.a.cum - pser(cx, ("68",)).a.cum) / cx.n)
    if cx.J1 is None:
        cx.vigil("blue", "Pas de FEC N-1 : variations N/N-1 non calculées.")
    anomalies_comptes(cx)
    onglets.append(("Points de vigilance", onglet_vigilance(cx)))
    notes = pied_notes(["Recettes = comptes de la classe 70 (pas de distinction 706/707/708 en BNC) ; les % « recettes » sont calculés sur ces recettes.",
                        "Les rétrocessions d'honoraires sont supposées enregistrées au compte 622 ; les cotisations personnelles de l'exploitant au compte 646 : à vérifier selon le plan du dossier.",
                        "Scénarios : charges variables = comptes 622 et 60 ; autres charges traitées comme fixes ; résultat avant impôt."])
    return onglets, resume, notes


# --------------------------------------------------------------------------- SCI (IR et IS)

def _construire_sci(cx, is_):
    J, J1 = cx.J, cx.J1
    i = cx.n - 1
    ann = 12 / cx.n
    loyers = pser(cx, ("70", "752"), -1)
    c7, c6 = pser(cx, ("7",), -1), pser(cx, ("6",))
    non_cash = pser(cx, ("78", "79"), -1)
    autres_pr = c7 - loyers - non_cash
    interets = pser(cx, ("66",))
    dot = pser(cx, ("68",))
    impot = pser(cx, ("69",))
    courantes = c6 - interets - dot - impot
    cf_expl = loyers + autres_pr - courantes
    capital = P(J.ser_mvt(("164",), 1).clip0(), J1.ser_mvt(("164",), 1).clip0() if J1 is not None else None)
    annuite = interets + capital
    cf_net = cf_expl - annuite
    res = c7 - c6
    caf = res + dot - pser(cx, ("78",), -1)
    t = {"treso": J.ser(("512", "514", "53", "519", "511"), 1).run()}
    t1 = {"treso": J1.ser(("512", "514", "53", "519", "511"), 1).run()} if J1 is not None else None
    loc = J.ser(("411", "413", "416", "418", "491"), 1).run()
    base = loyers.a.cum
    crd = -J.ser(("164",), 1).run().v[i]
    couv = (cf_expl.a.cum / annuite.a.cum) if annuite.a.cum > 0.5 else None
    resume = [
        f"Loyers et revenus locatifs (70, 752) cumul : {fm(base)} €" + (f" (N-1 : {fm(loyers.b.cum)} €, {pc(evol(base, loyers.b.cum))})" if loyers.b is not None and loyers.b.cum else ""),
        f"Charges courantes (hors intérêts, amortissements, IS) : {fm(courantes.a.cum)} € ({pc(part(courantes.a.cum, base))} des loyers) · cash-flow d'exploitation : {fm(cf_expl.a.cum)} €",
        f"Annuité d'emprunt (intérêts {fm(interets.a.cum)} € + capital {fm(capital.a.cum)} €) : {fm(annuite.a.cum)} € · cash-flow net avant impôt : {fm(cf_net.a.cum)} €"
        + (f" · couverture de l'annuité : {fm(couv, 2)}" if couv is not None else ""),
        f"Résultat comptable : {fm(res.a.cum)} €" + (f" · CAF : {fm(caf.a.cum)} €" if is_ else ""),
        f"Trésorerie fin de période : {fm(t['treso'].v[i])} € · capital restant dû (164) : {fm(crd)} €",
    ]
    cartes = [("Loyers", fm(base) + " €", f"Dernier mois {fm(loyers.a.v[i])} €" + (f" · N-1 {badge(evol_s(base, loyers.b.cum), True)}" if loyers.b is not None else ""), "card-m"),
              ("Cash-flow d'exploitation", fm(cf_expl.a.cum) + " €", f"{pc(part(cf_expl.a.cum, base))} des loyers", ""),
              ("Cash-flow net avant impôt", fm(cf_net.a.cum) + " €", f"après annuité de {fm(annuite.a.cum)} €", "card-m"),
              ("Trésorerie", fm(t["treso"].v[i]) + " €", f"fin {cx.labels[i]}", ""),
              ("Capital restant dû", fm(crd) + " €", "comptes 164", "")]
    rows = [("Loyers encaissés ou facturés", loyers.a, loyers.b, True, ""), ("Charges courantes", courantes.a, courantes.b, False, ""),
            ("Cash-flow d'exploitation", cf_expl.a, cf_expl.b, True, "rt"), ("Annuité d'emprunt", annuite.a, annuite.b, False, ""),
            ("Cash-flow net avant impôt", cf_net.a, cf_net.b, True, "rt"), ("Résultat comptable", res.a, res.b, True, "")]
    h1 = synthese(cx, cartes, rows, [("Loyers", loyers.a, C["terra"]), ("Charges courantes", courantes.a, C["ocre"]), ("Cash-flow net", cf_net.a, C["vert"])])
    # cumul
    h2 = tableau_mensuel(cx, [row("Revenus locatifs (70, 752)", loyers, "rt"), row("Autres produits (hors reprises)", autres_pr),
                              row("Charges courantes", courantes, "", False), row("Cash-flow d'exploitation", cf_expl, "rh"),
                              row("Intérêts d'emprunt (66)", interets, "", False), row("Capital remboursé (débit 164)", capital, "", False),
                              row("Cash-flow net avant impôt", cf_net, "rh"),
                              *([row("Dotations aux amortissements (68)", dot, "", False), row("Impôt sur les sociétés (695)", impot, "", False)] if is_ else []),
                              row("Résultat comptable (classe 7 − classe 6)", res, "rt")], base, "% loyers")
    # revenus locatifs par compte
    lig = lignes_par_compte(cx, ("70", "752"), -1, total="Total revenus locatifs")
    h3 = tableau_mensuel(cx, lig, base, "% loyers") if lig else "<p>Aucun revenu locatif (70, 752).</p>"
    occ = []
    for c in J.comptes(("70", "752")):
        s = J.ser_compte(c, -1)
        actifs = mois_actifs(s)
        if actifs:
            occ.append(("", [e(f"{c} {J.lib.get(c, '')[:30]}"), f"{actifs} / {cx.n}", fm(s.cum / actifs), tb.pc(actifs / cx.n * 100, 0)]))
            if actifs < cx.n and cx.n >= 3:
                cx.vigil("amber", f"Compte {e(c)} {e(J.lib.get(c, ''))} : loyers constatés sur {actifs} mois seulement sur {cx.n} (vacance, loyer non facturé ou facturation décalée).")
    if occ:
        h3 += "<h3>Mois facturés par compte de revenus (indicatif de taux d'occupation)</h3>" + cx.R.table(["Compte", "Mois avec loyer", "Loyer moyen / mois facturé", "Taux de mois facturés"], occ,
              "Indication tirée du FEC : seul un suivi locatif (baux, quittancement) donne le taux d'occupation réel.")
    h3 += "<h3>Créances locataires (411-418) en fin de mois</h3>" + cx.R.canvas(spec_line(cx.labels, [dict(ds("Créances locataires", loc.v, C["ocre"]), fill=False, tension=0.25)]), 200)
    h3 += barres_mensuelles(cx, "Loyers mensuels, N et N-1", loyers)
    if base > 0 and loc.v[i] > 2 * base / cx.n:
        cx.vigil("red", f"Créances locataires élevées : {fm(loc.v[i])} € soit {fm(loc.v[i] / (base / cx.n), 1)} mois de loyers (impayés possibles).")
    # charges
    groupes = [("Intérêts d'emprunt (66)", ("66",), 1, (), False), ("Taxes foncières et autres impôts (63)", ("63",), 1, (), False),
               ("Entretien et réparations (615)", ("615",), 1, (), False), ("Assurances (616)", ("616",), 1, (), False),
               ("Charges de copropriété et syndic (614)", ("614",), 1, (), False), ("Honoraires de gestion, comptables, juridiques (622)", ("622",), 1, (), False),
               ("Frais bancaires (627)", ("627",), 1, (), False)] + ([("Amortissements (68)", ("68",), 1, (), False), ("Impôt sur les sociétés (69)", ("69",), 1, (), False)] if is_ else [("Amortissements et impôts (68, 69)", ("68", "69"), 1, (), False)])
    pd = postes_avec_reste(cx, groupes, c6)
    h4 = tab_postes(cx, pd, base, "% loyers", "Total charges", c6)
    h4 += donut(cx, "Répartition des charges", [(l, pr, 1, ex) for l, pr, s_, ex, b in groupes])
    h4 += top_comptes(cx, "Dix premiers comptes de charges (cumul)", ("6",))
    # cash-flow locatif
    cfr = [row("Revenus locatifs", loyers, "rt"), row("− Charges courantes", -courantes, ""), row("= Cash-flow d'exploitation", cf_expl, "rh"),
           row("− Intérêts d'emprunt", -interets, ""), row("− Capital remboursé", -capital, ""), row("= CASH-FLOW NET AVANT IMPÔT", cf_net, "rh")]
    h5 = tableau_mensuel(cx, cfr, base, "% loyers")
    h5 += ("<h3>Couverture de l'annuité</h3>" + cx.R.table(["", "N"] + (["N-1"] if cx.R.has_n1 else []),
           [("", ["Cash-flow d'exploitation / annuité", fm(couv, 2) if couv is not None else "—"] + ([fm(cf_expl.b.cum / annuite.b.cum, 2) if cx.R.has_n1 and annuite.b is not None and annuite.b.cum > 0.5 else "—"] if cx.R.has_n1 else []))],
           "Supérieure à 1 : les loyers couvrent les charges et l'annuité. Capital remboursé = mouvements débiteurs des comptes 164 hors à-nouveaux.")) if True else ""
    if couv is not None and couv < 1:
        cx.vigil("red", f"Cash-flow d'exploitation inférieur à l'annuité d'emprunt (couverture {fm(couv, 2)}) : la SCI ne couvre pas son remboursement par ses loyers.")
    elif couv is not None and couv < 1.2:
        cx.vigil("amber", f"Couverture de l'annuité faible ({fm(couv, 2)}).")
    h5 += barres_mensuelles(cx, "Cash-flow net mensuel, N et N-1", cf_net, C["vert"])
    # rentabilite
    vb = cx.opts.get("valeur_bien")
    sm = cx.opts.get("surface_m2")
    lignes_r = [("Charges courantes / loyers", tb.pc(part(courantes.a.cum, base))), ("Intérêts / loyers", tb.pc(part(interets.a.cum, base))),
                ("Annuité / loyers", tb.pc(part(annuite.a.cum, base)))]
    if vb:
        lignes_r += [("Rendement brut (loyers annualisés / valeur du bien)", tb.pc(part(base * ann, vb))),
                     ("Rendement net de charges courantes (annualisé)", tb.pc(part((base - courantes.a.cum) * ann, vb)))]
        resume.append(f"Rendement brut : {pc(part(base * ann, vb))} ; net de charges courantes : {pc(part((base - courantes.a.cum) * ann, vb))} (valeur du bien fournie : {fm(vb)} €).")
    if sm:
        lignes_r.append(("Coût de détention par m² (charges courantes + intérêts, annualisé)", fm((courantes.a.cum + interets.a.cum) * ann / sm, 1) + " €/m²"))
    h6 = "<h3>Rentabilité et coût de détention</h3>" + cx.R.table(["Indicateur", "N"], [("", [e(l), v]) for l, v in lignes_r],
          ("" if vb else "Valeur du bien non fournie (paramètre valeur_bien) : rendement brut et net non calculés. ") + ("" if sm else "Surface non fournie (paramètre surface_m2) : coût au m² non calculé."))
    # tresorerie + emprunts
    cr = []
    for c in J.comptes(("164",)):
        crd_c = -J.ser_compte(c).run().v[i]
        rem = max(0.0, sum(max(0.0, x) for x in J.mvt[c])) if c in J.mvt else 0.0
        cr.append(("", [e(f"{c} {J.lib.get(c, '')[:30]}"), fm(crd_c), fm(rem)]))
    extra = ""
    if cr:
        extra = "<h3>Échéances d'emprunts</h3>" + cx.R.table(["Emprunt (compte 164)", "Capital restant dû en fin de période", "Capital remboursé sur la période"], cr,
                f"Intérêts de la période : {fm(interets.a.cum)} € ; annuité moyenne mensuelle : {fm(annuite.a.cum / cx.n)} €. La date de dernière échéance et le taux ne figurent pas dans le FEC : à reprendre du tableau d'amortissement.")
    if annuite.a.cum > 0 and t["treso"].v[i] < 3 * annuite.a.cum / cx.n:
        cx.vigil("amber", f"Trésorerie ({fm(t['treso'].v[i])} €) inférieure à trois mois d'annuité ({fm(3 * annuite.a.cum / cx.n)} €).")
    ht = onglet_tresorerie(cx, t, t1, None, extra=extra)
    # scenarios
    loy_a, cfn_a = base * ann, cf_net.a.cum * ann
    srows, labels, vals = [], [], []
    srows.append(("", ["Central (extrapolation du cumul)", fm(loy_a), fm(cfn_a), "—"]))
    labels.append("Central")
    vals.append(cfn_a)
    for v in (1, 2, 3):
        pert = loy_a * v / 12
        srows.append(("", [f"Vacance de {v} mois", fm(loy_a - pert), fm(cfn_a - pert), fm(-pert)]))
        labels.append(f"Vacance {v} m.")
        vals.append(cfn_a - pert)
    for w in (5000, 10000):
        srows.append(("", [f"Travaux imprévus de {fm(w)} €", fm(loy_a), fm(cfn_a - w), fm(-w)]))
        labels.append(f"Travaux {fm(w)} €")
        vals.append(cfn_a - w)
    hsc = cx.R.table(["Scénario (annuel)", "Loyers", "Cash-flow net avant impôt", "Écart au central"], srows,
                     "Extrapolation linéaire du cumul de la période sur 12 mois ; charges et annuité inchangées. Les montants de travaux sont des hypothèses d'illustration, pas des prévisions. "
                     "Scénario de revente non calculé : il suppose valeur d'acquisition, valeur de marché et durée de détention, absentes du FEC.")
    hsc += cx.R.canvas(spec_bar(labels, [ds("Cash-flow net avant impôt annuel", vals, C["terra"])]), 240)
    # vigilance
    variations_vigilance(cx, [("Loyers", loyers.a, loyers.b, True), ("Charges courantes", courantes.a, courantes.b, False), ("Intérêts d'emprunt", interets.a, interets.b, False)], SEUIL_VARIATION)
    if res.a.cum < 0:
        cx.vigil("blue" if is_ else "amber", f"Résultat comptable négatif : {fm(res.a.cum)} €" + (" (déficit foncier possible : à analyser selon la nature des charges)." if not is_ else "."))
    if not is_ and (abs(dot.a.cum) > 0.5 or abs(impot.a.cum) > 0.5):
        cx.vigil("amber", f"SCI à l'IR avec des écritures d'amortissement (68 : {fm(dot.a.cum)} €) ou d'IS (69 : {fm(impot.a.cum)} €) : situation inhabituelle, à vérifier (option pour l'IS ?).")
    if is_ and abs(dot.a.cum) < 0.5 and J.comptes(("213", "2131", "214")) and cx.n >= 12:
        cx.vigil("amber", "SCI à l'IS avec immeuble à l'actif mais aucun amortissement constaté sur la période : vérifier si les dotations sont passées en fin d'exercice.")
    tresorerie_et_alertes(cx, t, (c6.a.cum - dot.a.cum) / cx.n)
    if cx.J1 is None:
        cx.vigil("blue", "Pas de FEC N-1 : variations N/N-1 non calculées.")
    anomalies_comptes(cx)
    onglets = [("Synthèse", h1), ("Tableau cumul", h2), ("Revenus locatifs", h3), ("Charges", h4), ("Cash-flow locatif", h5),
               ("Rentabilité patrimoniale", h6), ("Trésorerie & emprunts", ht), ("Scénarios", hsc), ("Points de vigilance", onglet_vigilance(cx))]
    notes = pied_notes(["Revenus locatifs = comptes 70 et 752 ; charges courantes = classe 6 hors intérêts (66), amortissements (68) et impôt (69) ; autres produits = classe 7 hors loyers et hors reprises (78, 79).",
                        "Annuité = intérêts (66) + capital remboursé (mouvements débiteurs du compte 164 hors à-nouveaux). Pas de BFR en SCI.",
                        "SCI à l'" + ("IS : l'amortissement de l'immeuble est déductible ; la CAF = résultat + dotations − reprises." if is_ else "IR : les amortissements ne sont pas déductibles ; le résultat comptable n'est pas le revenu foncier imposable.")])
    return onglets, resume, notes


def construire_sci_ir(cx):
    return _construire_sci(cx, False)


def construire_sci_is(cx):
    return _construire_sci(cx, True)


# --------------------------------------------------------------------------- Association loi 1901

def _fonds_dedies(cx):
    """Tableau des fonds dedies (compte 19) : ouverture, dotations (689), utilisations (789), solde de fin."""
    J = cx.J
    i = cx.n - 1
    rows, total = [], 0.0
    for c in J.comptes(("19",)):
        ouv = -J.ouv.get(c, 0.0)
        fin = -J.ser_compte(c).run().v[i]
        mouv = fin - ouv
        rows.append(("", [e(f"{c} {J.lib.get(c, '')[:34]}"), fm(ouv), fm(mouv), fm(fin)]))
        total += fin
    return rows, total


def construire_association(cx):
    J, J1 = cx.J, cx.J1
    i = cx.n - 1
    ann = 12 / cx.n
    res_p = pser(cx, ("7",), -1)
    emp = pser(cx, ("6",))
    solde = res_p - emp
    base = res_p.a.cum
    cotis = pser(cx, ("756",), -1)
    dons = pser(cx, ("754",), -1)
    subv = pser(cx, ("74",), -1)
    ventes = pser(cx, ("70",), -1)
    fonds = pser(cx, ("789",), -1)
    t = {"treso": J.ser(("512", "514", "53", "519", "511"), 1).run()}
    subv_cr = J.ser(("441", "4418", "4411"), 1).run()
    cli = J.ser(("411", "413", "416", "418", "491"), 1).run()
    four = J.ser(("401", "403", "408"), -1).run()
    t["subv"], t["clients"], t["fournisseurs"] = subv_cr, cli, four
    t["bfr"] = subv_cr + cli - four
    t1 = None
    if J1 is not None:
        s1 = J1.ser(("441", "4418", "4411"), 1).run()
        c1 = J1.ser(("411", "413", "416", "418", "491"), 1).run()
        f1 = J1.ser(("401", "403", "408"), -1).run()
        t1 = {"treso": J1.ser(("512", "514", "53", "519", "511"), 1).run(), "subv": s1, "clients": c1, "fournisseurs": f1, "bfr": s1 + c1 - f1}
    emploi_mens = (emp.a.cum - pser(cx, ("68", "689")).a.cum) / cx.n
    mois_fonct = t["treso"].v[i] / emploi_mens if emploi_mens > 0 else None
    fd_rows, fd_total = _fonds_dedies(cx)
    sub_comptes = sorted(((c, J.ser_compte(c, -1).cum) for c in J.comptes(("74",))), key=lambda x: -x[1])
    dep = (sub_comptes[0][1] / base * 100) if sub_comptes and base > 0 else None
    resume = [
        f"Ressources (classe 7) cumul : {fm(base)} €" + (f" (N-1 : {fm(res_p.b.cum)} €, {pc(evol(base, res_p.b.cum))})" if res_p.b is not None and res_p.b.cum else ""),
        f"Emplois (classe 6) : {fm(emp.a.cum)} € ({pc(part(emp.a.cum, base))} des ressources) · résultat : {fm(solde.a.cum)} €" + (f" (N-1 : {fm(solde.b.cum)} €)" if solde.b is not None else ""),
        f"Structure : subventions (74) {pc(part(subv.a.cum, base))}, cotisations (756) {pc(part(cotis.a.cum, base))}, dons et collectes (754) {pc(part(dons.a.cum, base))}, ventes et prestations (70) {pc(part(ventes.a.cum, base))}",
        (f"Dépendance à la première subvention ({sub_comptes[0][0]} {J.lib.get(sub_comptes[0][0], '')}) : {pc(dep)} des ressources" if dep is not None else "Aucune subvention (compte 74) sur la période."),
        f"Trésorerie fin de période : {fm(t['treso'].v[i])} €" + (f" soit {fm(mois_fonct, 1)} mois de fonctionnement" if mois_fonct is not None else "") + f" · fonds dédiés au bilan : {fm(fd_total)} €",
    ]
    cartes = [("Total ressources", fm(base) + " €", f"Dernier mois {fm(res_p.a.v[i])} €" + (f" · N-1 {badge(evol_s(base, res_p.b.cum), True)}" if res_p.b is not None else ""), "card-m"),
              ("Total emplois", fm(emp.a.cum) + " €", f"{pc(part(emp.a.cum, base))} des ressources", ""),
              ("Résultat", fm(solde.a.cum) + " €", "un résultat proche de 0 est normal en association" , "card-m"),
              ("Trésorerie", fm(t["treso"].v[i]) + " €", (f"{fm(mois_fonct, 1)} mois de fonctionnement" if mois_fonct is not None else f"fin {cx.labels[i]}"), ""),
              ("Fonds dédiés", fm(fd_total) + " €", "à consommer (comptes 19)", "")]
    rows = [("Ressources", res_p.a, res_p.b, True, ""), ("Emplois", emp.a, emp.b, False, ""), ("Résultat", solde.a, solde.b, True, "rt")]
    h1 = synthese(cx, cartes, rows, [("Ressources", res_p.a, C["terra"]), ("Emplois", emp.a, C["ocre"]), ("Résultat", solde.a, C["vert"])])
    g_res = [("Ventes, prestations, produits d'activité (70)", ("70",), -1, (), True), ("Subventions et concours publics (74)", ("74",), -1, (), True),
             ("Cotisations (756)", ("756",), -1, (), True), ("Dons, collectes, mécénat (754)", ("754",), -1, (), True),
             ("Reprises de fonds dédiés / report de ressources (789)", ("789",), -1, (), True), ("Produits financiers et exceptionnels (76, 77)", ("76", "77"), -1, (), True)]
    pr = postes_avec_reste(cx, g_res, res_p)
    g_emp = [("Achats (60)", ("60",), 1, (), False), ("Services extérieurs et autres (61, 62)", ("61", "62"), 1, (), False), ("Impôts et taxes (63)", ("63",), 1, (), False),
             ("Personnel (64)", ("64",), 1, (), False), ("Autres charges de gestion (65)", ("65",), 1, (), False), ("Charges financières et exceptionnelles (66, 67)", ("66", "67"), 1, (), False),
             ("Dotations aux amortissements et provisions (68 hors 689)", ("68",), 1, ("689",), False), ("Engagements à réaliser sur ressources affectées (689)", ("689",), 1, (), False)]
    pe = postes_avec_reste(cx, g_emp, emp)
    h2 = tableau_mensuel(cx, [row("Total ressources", res_p, "rt")] + [(l, p.a, p.b, "", b) for l, p, b in pr if l != "Autres" or abs(p.a.cum) > 0.5] +
                         [row("Total emplois", emp, "rt", False), row("Résultat", solde, "rh")], base, "% ressources")
    h3 = tab_postes(cx, pr, base, "% ressources", "Total ressources", res_p, True)
    sp = lignes_par_compte(cx, ("74",), -1)
    if sp:
        h3 += "<h3>Subventions par compte (financeur)</h3>" + tableau_mensuel(cx, sp, base, "% ressources")
    h3 += donut(cx, "Répartition des ressources", [(l, pr_, s_, ex) for l, pr_, s_, ex, b in g_res])
    h3 += barres_mensuelles(cx, "Ressources mensuelles, N et N-1", res_p)
    h4 = tab_postes(cx, pe, base, "% ressources", "Total emplois", emp)
    h4 += donut(cx, "Répartition des emplois", [(l, pr_, s_, ex) for l, pr_, s_, ex, b in g_emp])
    h4 += top_comptes(cx, "Dix premiers comptes d'emplois (cumul)", ("6",))
    # equilibre budgetaire
    eq_rows = [row("Ressources", res_p, "rt"), row("− Emplois", -emp, ""), row("= RÉSULTAT", solde, "rh")]
    h5 = tableau_mensuel(cx, eq_rows, base, "% ressources")
    effet_fd = pser(cx, ("689",)) - pser(cx, ("789",))
    h5 += cx.R.table(["Lecture du résultat", "Montant"], [("", ["Résultat après fonds dédiés", fm(solde.a.cum)]),
                     ("", ["Dont engagements à réaliser (689) − reports (789)", fm(effet_fd.a.cum)]),
                     ("", ["Résultat avant effet des fonds dédiés", fm(solde.a.cum + effet_fd.a.cum)]),
                     ("", ["Ratio emplois / ressources", tb.pc(part(emp.a.cum, base))])],
                     "Budget prévisionnel non fourni : pas de colonne d'écart au budget. Un ratio proche de 100 % est le comportement attendu hors années exceptionnelles.")
    h5 += barres_mensuelles(cx, "Résultat mensuel, N et N-1", solde, C["vert"])
    # structure de financement
    sf = [("Subventions publiques (74)", part(subv.a.cum, base), part(subv.b.cum, res_p.b.cum) if subv.b is not None and res_p.b is not None and res_p.b.cum else None),
          ("Cotisations (756)", part(cotis.a.cum, base), part(cotis.b.cum, res_p.b.cum) if cotis.b is not None and res_p.b is not None and res_p.b.cum else None),
          ("Dons, collectes, mécénat (754)", part(dons.a.cum, base), part(dons.b.cum, res_p.b.cum) if dons.b is not None and res_p.b is not None and res_p.b.cum else None),
          ("Ventes et prestations (70)", part(ventes.a.cum, base), part(ventes.b.cum, res_p.b.cum) if ventes.b is not None and res_p.b is not None and res_p.b.cum else None)]
    h6 = "<h3>Origine des ressources</h3>" + cx.R.table(["Origine", "% des ressources N"] + (["% N-1"] if cx.R.has_n1 else []),
         [("", [e(l), tb.pc(a)] + ([tb.pc(b)] if cx.R.has_n1 else [])) for l, a, b in sf],
         "Le compte 74 regroupe les subventions et concours publics ; des financements privés (fondations) y sont parfois aussi enregistrés : à vérifier compte par compte.")
    if sub_comptes:
        h6 += "<h3>Dépendance par financeur (comptes 74)</h3>" + cx.R.table(["Compte", "Montant", "% des ressources"],
              [("", [e(f"{c} {J.lib.get(c, '')[:34]}"), fm(v), tb.pc(part(v, base))]) for c, v in sub_comptes if abs(v) > 0.5])
        if dep is not None and dep >= 40:
            cx.vigil("amber" if dep < 60 else "red", f"Forte dépendance à un financeur : {pc(dep, 0)} des ressources viennent du compte {e(sub_comptes[0][0])} {e(J.lib.get(sub_comptes[0][0], ''))}.")
    # tresorerie
    postes = [("Créances de subventions (441)", "subv", True), ("Créances usagers et clients (411-418)", "clients", True), ("Dettes fournisseurs (401-408)", "fournisseurs", False)]
    extra = ""
    if fd_rows:
        extra = "<h3>Fonds dédiés (comptes 19)</h3>" + cx.R.table(["Compte", "Solde d'ouverture", "Variation de la période", "Solde en fin de période"], fd_rows + [("rt", ["Total", "", "", fm(fd_total)])],
                "Ressources affectées reçues et non encore utilisées : engagement vis-à-vis des financeurs, à ne pas confondre avec une trésorerie disponible.")
        if mois_fonct is not None and t["treso"].v[i] < fd_total:
            cx.vigil("amber", f"La trésorerie ({fm(t['treso'].v[i])} €) est inférieure aux fonds dédiés ({fm(fd_total)} €) : une partie des fonds affectés a déjà été dépensée ou immobilisée.")
    if mois_fonct is not None:
        extra += cx.R.box("blue", "Trésorerie en mois de fonctionnement", [f"{fm(mois_fonct, 1)} mois d'emplois décaissables (emplois mensuels moyens hors dotations : {fm(emploi_mens)} €)."])
        if mois_fonct < 1:
            cx.vigil("red", f"Trésorerie inférieure à un mois de fonctionnement ({fm(mois_fonct, 1)} mois).")
        elif mois_fonct < 3:
            cx.vigil("amber", f"Trésorerie de {fm(mois_fonct, 1)} mois de fonctionnement (repère habituel : 3 mois).")
    ht = onglet_tresorerie(cx, t, t1, None, libelle_bfr="BFR (créances subventions + usagers − fournisseurs)", extra=extra, postes=postes, delai=False)
    # scenarios
    res_a, emp_a = base * ann, emp.a.cum * ann
    srows, labels, vals = [("", ["Central (extrapolation du cumul)", fm(res_a), fm(emp_a), fm(res_a - emp_a)])], ["Central"], [res_a - emp_a]
    if sub_comptes and sub_comptes[0][1] > 0:
        perte = sub_comptes[0][1] * ann
        srows.append(("", [f"Perte de la subvention {sub_comptes[0][0]} {J.lib.get(sub_comptes[0][0], '')[:24]}", fm(res_a - perte), fm(emp_a), fm(res_a - perte - emp_a)]))
        labels.append("Perte subvention majeure")
        vals.append(res_a - perte - emp_a)
    cd = (cotis.a.cum + dons.a.cum) * ann
    for pct_, nom in ((-0.10, "Cotisations et dons −10 %"), (0.10, "Cotisations et dons +10 %")):
        if cd > 0:
            srows.append(("", [nom, fm(res_a + cd * pct_), fm(emp_a), fm(res_a + cd * pct_ - emp_a)]))
            labels.append(nom)
            vals.append(res_a + cd * pct_ - emp_a)
    hsc = cx.R.table(["Scénario (annuel)", "Ressources", "Emplois", "Résultat"], srows,
                     "Extrapolation linéaire du cumul sur 12 mois. Perte d'une subvention : les emplois sont supposés inchangés (cas le plus défavorable, sans réduction d'activité). Hypothèses de simulation, pas des prévisions.")
    hsc += cx.R.canvas(spec_bar(labels, [ds("Résultat annuel projeté", vals, C["terra"])]), 240)
    # vigilance
    if solde.a.cum < 0:
        cx.vigil("amber", f"Résultat déficitaire sur la période : {fm(solde.a.cum)} €.")
    variations_vigilance(cx, [("Ressources", res_p.a, res_p.b, True), ("Subventions (74)", subv.a, subv.b, True), ("Cotisations (756)", cotis.a, cotis.b, True),
                              ("Dons (754)", dons.a, dons.b, True), ("Personnel (64)", pser(cx, ("64",)).a, pser(cx, ("64",)).b, False), ("Total emplois", emp.a, emp.b, False)], SEUIL_VARIATION)
    if cx.J1 is None:
        cx.vigil("blue", "Pas de FEC N-1 : variations N/N-1 non calculées.")
    if J.comptes(("86", "87")):
        cx.vigil("blue", "Des contributions volontaires en nature (classes 86 et 87) sont présentes : elles ne sont pas incluses dans les totaux ci-dessus.")
    anomalies_comptes(cx)
    onglets = [("Synthèse", h1), ("Tableau cumul", h2), ("Ressources", h3), ("Emplois", h4), ("Équilibre budgétaire", h5), ("Structure de financement", h6),
               ("Trésorerie & fonds dédiés", ht), ("Scénarios", hsc), ("Points de vigilance", onglet_vigilance(cx))]
    notes = pied_notes(["Association : ressources = classe 7, emplois = classe 6 ; les % sont calculés sur le total des ressources. Les classes 86-87 (bénévolat) sont exclues.",
                        "Le résultat est après effet des fonds dédiés (689 / 789). Aucun budget prévisionnel n'est utilisé (non fourni)."])
    return onglets, resume, notes


# --------------------------------------------------------------------------- Association ESMS

def construire_esms(cx):
    J, J1 = cx.J, cx.J1
    i = cx.n - 1
    ann = 12 / cx.n
    prod = pser(cx, ("7",), -1)
    emp = pser(cx, ("6",))
    solde = prod - emp
    base = prod.a.cum
    g1 = pser(cx, ("60",))
    g2 = pser(cx, ("64", "631", "633"))
    g3 = emp - g1 - g2
    tarif = pser(cx, ("73",), -1)
    exploit = pser(cx, ("70",), -1)
    t = {"treso": J.ser(("512", "514", "53", "519", "511"), 1).run()}
    cr = J.ser(("411", "413", "416", "418", "441", "468", "491"), 1).run()
    four = J.ser(("401", "403", "408"), -1).run()
    t["clients"], t["fournisseurs"] = cr, four
    t["bfr"] = cr - four
    t1 = None
    if J1 is not None:
        c1, f1 = J1.ser(("411", "413", "416", "418", "441", "468", "491"), 1).run(), J1.ser(("401", "403", "408"), -1).run()
        t1 = {"treso": J1.ser(("512", "514", "53", "519", "511"), 1).run(), "clients": c1, "fournisseurs": f1, "bfr": c1 - f1}
    jr, jt = cx.opts.get("journees_realisees"), cx.opts.get("journees_theoriques")
    try:
        jr = float(str(jr).replace(" ", "").replace(",", ".")) if jr not in (None, "") else None
        jt = float(str(jt).replace(" ", "").replace(",", ".")) if jt not in (None, "") else None
    except ValueError:
        jr = jt = None
    taux_occ = (jr / jt * 100) if jr and jt else None
    part_g2 = part(g2.a.cum, emp.a.cum)
    resume = [
        f"Produits (classe 7) cumul : {fm(base)} € dont tarification (73) {fm(tarif.a.cum)} € et produits d'exploitation (70) {fm(exploit.a.cum)} €" + (f" (N-1 total : {fm(prod.b.cum)} €, {pc(evol(base, prod.b.cum))})" if prod.b is not None and prod.b.cum else ""),
        f"Charges (classe 6) : {fm(emp.a.cum)} € · résultat global : {fm(solde.a.cum)} €" + (f" (N-1 : {fm(solde.b.cum)} €)" if solde.b is not None else ""),
        f"Groupes (répartition à valider) : G1 exploitation courante {fm(g1.a.cum)} € ({pc(part(g1.a.cum, emp.a.cum))}) · G2 personnel {fm(g2.a.cum)} € ({pc(part_g2)}) · G3 structure {fm(g3.a.cum)} € ({pc(part(g3.a.cum, emp.a.cum))})",
        (f"Taux d'occupation : {pc(taux_occ)} ({fm(jr)} journées réalisées / {fm(jt)} théoriques)" if taux_occ is not None else "Taux d'occupation : non calculé (journées réalisées et théoriques non fournies)."),
        f"Trésorerie fin de période : {fm(t['treso'].v[i])} € · créances (résidents et financeurs) : {fm(cr.v[i])} €",
    ]
    if jr:
        resume.append(f"Coût moyen par journée réalisée : {fm(emp.a.cum / jr, 2)} € ; produit moyen par journée : {fm(base / jr, 2)} €.")
    cartes = [("Taux d'occupation", tb.pc(taux_occ) if taux_occ is not None else "n.c.", (f"{fm(jr)} / {fm(jt)} journées" if taux_occ is not None else "journées non fournies"), "card-m"),
              ("Total produits", fm(base) + " €", f"Dont tarification {pc(part(tarif.a.cum, base))}" + (f" · N-1 {badge(evol_s(base, prod.b.cum), True)}" if prod.b is not None else ""), ""),
              ("Résultat global", fm(solde.a.cum) + " €", "résultat par section : voir note", "card-m"),
              ("Part du personnel (G2)", tb.pc(part_g2), "des charges", ""),
              ("Trésorerie", fm(t["treso"].v[i]) + " €", f"fin {cx.labels[i]}", "")]
    rows = [("Produits", prod.a, prod.b, True, ""), ("Charges", emp.a, emp.b, False, ""), ("Résultat global", solde.a, solde.b, True, "rt"),
            ("G1 — exploitation courante", g1.a, g1.b, False, ""), ("G2 — personnel", g2.a, g2.b, False, ""), ("G3 — structure", g3.a, g3.b, False, "")]
    h1 = synthese(cx, cartes, rows, [("Produits", prod.a, C["terra"]), ("Charges", emp.a, C["ocre"]), ("Résultat", solde.a, C["vert"])])
    h2 = tableau_mensuel(cx, [row("Produits de la tarification (73)", tarif), row("Produits d'exploitation (70)", exploit),
                              row("Autres produits", prod - tarif - exploit), row("Total produits", prod, "rt"),
                              row("G1 — Exploitation courante (60)", g1, "", False), row("G2 — Personnel (64, 631, 633)", g2, "", False),
                              row("G3 — Structure (61, 62, 63 hors 631/633, 65 à 69)", g3, "", False), row("Total charges", emp, "rt", False),
                              row("Résultat global", solde, "rh")], base, "% produits")
    gp = [("Produits de la tarification (73)", ("73",), -1, (), True), ("Produits d'exploitation, hébergement et prestations (70)", ("70",), -1, (), True),
          ("Subventions (74)", ("74",), -1, (), True), ("Autres produits de gestion (75)", ("75",), -1, (), True),
          ("Reprises et reports (78)", ("78",), -1, (), True), ("Produits financiers et exceptionnels (76, 77)", ("76", "77"), -1, (), True)]
    pp = postes_avec_reste(cx, gp, prod)
    h3 = tab_postes(cx, pp, base, "% produits", "Total produits", prod, True)
    lt = lignes_par_compte(cx, ("73", "70"), -1)
    if lt:
        h3 += "<h3>Détail par compte (tarification et exploitation)</h3>" + tableau_mensuel(cx, lt, base, "% produits")
    h3 += donut(cx, "Répartition des produits", [(l, pr_, s_, ex) for l, pr_, s_, ex, b in gp])
    h3 += barres_mensuelles(cx, "Produits mensuels, N et N-1", prod)
    h3 += cx.R.box("blue", "Sections tarifaires", ["La ventilation hébergement / dépendance / soins et par financeur (résidents, Département, ARS, CPAM) n'est pas déductible du FEC sans comptabilité analytique : "
                                                  "elle n'est pas calculée. Si les comptes de produits sont subdivisés par section, leur détail figure dans le tableau par compte ci-dessus."])
    cg = [("G1 — Dépenses d'exploitation courante (60)", g1, False), ("G2 — Dépenses de personnel (64, 631, 633)", g2, False), ("G3 — Dépenses de structure (61, 62, 63 hors 631/633, 65 à 69)", g3, False), ("Total charges", emp, False)]
    h4 = table_postes(cx, "Charges par groupe fonctionnel", cg, base, "% produits")
    h4 += cx.R.table(["Part dans le total des charges", "N"] + (["N-1"] if cx.R.has_n1 else []),
        [("", [e(l), tb.pc(part(p.a.cum, emp.a.cum))] + ([tb.pc(part(p.b.cum, emp.b.cum)) if p.b is not None and emp.b is not None and emp.b.cum else "—"] if cx.R.has_n1 else [])) for l, p, b in cg[:3]],
        "Budget autorisé non fourni : pas de colonne « budget » ni de % consommé. Répartition G1/G2/G3 posée par convention (voir pied de page) : à valider au regard du cadre budgétaire de l'établissement.")
    h4 += donut(cx, "Répartition des charges par groupe", [("G1 exploitation courante", ("60",), 1, ()), ("G2 personnel", ("64", "631", "633"), 1, ()),
                                                           ("G3 structure", ("61", "62", "65", "66", "67", "68", "69"), 1, ())])
    h4 += top_comptes(cx, "Dix premiers comptes de charges (cumul)", ("6",))
    h5 = tableau_mensuel(cx, [row("Services extérieurs (61, 62)", pser(cx, ("61", "62")), "", False), row("Impôts et taxes hors taxes sur salaires (63)", pser(cx, ("63",), 1, ("631", "633")), "", False),
                              row("Achats (60)", g1, "", False)], base, "% produits") if J.comptes(("60", "61", "62", "63")) else ""
    h5 += tableau_mensuel(cx, lignes_par_compte(cx, ("60", "61", "62"), 1, bon=False, total="Total 60, 61, 62"), base, "% produits") if J.comptes(("60", "61", "62")) else ""
    # compte de resultat reglementaire
    pg1, pg2, pg3 = pser(cx, ("73",), -1), pser(cx, ("70", "71", "72", "74", "75", "79"), -1), pser(cx, ("76", "77", "78"), -1)
    cr_rows = [row("Produits groupe I — produits de la tarification (73)", pg1, "", True), row("Produits groupe II — autres produits d'exploitation (70-72, 74, 75, 79)", pg2),
               row("Produits groupe III — produits financiers et non encadrés (76, 77, 78)", pg3), row("TOTAL PRODUITS", prod, "rt"),
               row("Charges G1 — exploitation courante", g1, "", False), row("Charges G2 — personnel", g2, "", False), row("Charges G3 — structure", g3, "", False),
               row("TOTAL CHARGES", emp, "rt", False), row("RÉSULTAT GLOBAL (excédent / déficit)", solde, "rh")]
    h6 = tableau_mensuel(cx, cr_rows, base, "% produits") + cx.R.box("amber", "Limites de cette présentation", [
        "Présentation inspirée du compte de résultat réglementaire : la répartition en groupes est une convention à valider (cadre budgétaire normalisé de l'établissement).",
        "Résultat par section (hébergement, dépendance, soins) et affectation du résultat : non calculés, absents du FEC. Un excédent d'une section ne compense pas le déficit d'une autre (cloisonnement des financements)."])
    # indicateurs d'activite
    ind = [("Part du personnel (G2) dans les charges", tb.pc(part_g2)), ("Part des produits de tarification (73) dans les produits", tb.pc(part(tarif.a.cum, base)))]
    if taux_occ is not None:
        ind = [("Taux d'occupation", tb.pc(taux_occ)), ("Journées réalisées / théoriques", f"{fm(jr)} / {fm(jt)}"), ("Coût moyen par journée réalisée (total charges)", fm(emp.a.cum / jr, 2) + " €"),
               ("Charges de personnel par journée réalisée", fm(g2.a.cum / jr, 2) + " €"), ("Produit moyen par journée réalisée", fm(base / jr, 2) + " €")] + ind
    delai = (cr.v[i] / (base / cx.n) * 30) if base > 0 else None
    if delai is not None:
        ind.append(("Créances rapportées aux produits (jours, indicatif du délai de paiement des financeurs)", fm(delai) + " jours"))
    h7 = cx.R.table(["Indicateur", "N"], [("", [e(l), v]) for l, v in ind],
                    ("" if taux_occ is not None else "Journées non fournies (paramètres journees_realisees et journees_theoriques) : taux d'occupation et coûts par journée non calculés. ")
                    + "GMP/PMP, effectif ETP réel et autorisé : absents du FEC, non calculés.")
    h7 += barres_mensuelles(cx, "Produits mensuels, N et N-1", prod)
    ht = onglet_tresorerie(cx, t, t1, None, libelle_bfr="BFR (créances financeurs et résidents − fournisseurs)", postes=[("Créances résidents et financeurs (411-418, 441, 468)", "clients", True), ("Dettes fournisseurs (401-408)", "fournisseurs", False)], delai=False)
    fp = -J.ser(("10",), 1).run().v[i]
    ht += cx.R.box("blue", "Fonds propres", [f"Fonds propres (classe 10) en fin de période : {fm(fp)} €. L'affectation du résultat dépend des règles de l'autorité de tarification."])
    # scenarios
    prod_a, emp_a = base * ann, emp.a.cum * ann
    srows, labels, vals = [("", ["Central (extrapolation du cumul)", fm(prod_a), fm(emp_a), fm(prod_a - emp_a)])], ["Central"], [prod_a - emp_a]
    sensible = (tarif.a.cum + exploit.a.cum) * ann
    for pts in (2, 5):
        ratio = (pts / taux_occ) if taux_occ else pts / 100
        dp = sensible * ratio
        dg1 = g1.a.cum * ann * ratio
        nom = f"Taux d'occupation −{pts} points" if taux_occ else f"Activité −{pts} %"
        srows.append(("", [nom, fm(prod_a - dp), fm(emp_a - dg1), fm(prod_a - dp - (emp_a - dg1))]))
        labels.append(nom)
        vals.append(prod_a - dp - (emp_a - dg1))
    for gvt in (1, 2):
        dpers = g2.a.cum * ann * gvt / 100
        srows.append(("", [f"Personnel +{gvt} % (GVT)", fm(prod_a), fm(emp_a + dpers), fm(prod_a - emp_a - dpers)]))
        labels.append(f"Personnel +{gvt} %")
        vals.append(prod_a - emp_a - dpers)
    hsc = cx.R.table(["Scénario (annuel)", "Produits", "Charges", "Résultat"], srows,
                     "Extrapolation linéaire du cumul sur 12 mois. Baisse d'occupation : les produits de tarification et d'exploitation (73, 70) baissent proportionnellement, les achats (G1) aussi, personnel et structure inchangés. "
                     "Hypothèses de simulation, pas des prévisions. Scénario de renouvellement de convention tripartite non chiffré (aucune donnée dans le FEC).")
    hsc += cx.R.canvas(spec_bar(labels, [ds("Résultat annuel projeté", vals, C["terra"])]), 240)
    # vigilance
    if solde.a.cum < 0:
        cx.vigil("red", f"Déficit global sur la période : {fm(solde.a.cum)} €. Un déficit récurrent sur une section tarifaire est à documenter et à remonter à l'autorité de tarification.")
    if part_g2 is not None and part_g2 > 75:
        cx.vigil("amber", f"Personnel à {pc(part_g2, 0)} des charges, au-dessus de la fourchette habituelle de 65 à 75 %.")
    if taux_occ is not None and taux_occ < 90:
        cx.vigil("amber", f"Taux d'occupation de {pc(taux_occ)} : impact direct sur les recettes tarifaires.")
    if delai is not None and delai > 60:
        cx.vigil("amber", f"Créances élevées : environ {fm(delai)} jours de produits (financeurs et résidents), à rapprocher des délais de paiement habituels.")
    variations_vigilance(cx, [("Produits", prod.a, prod.b, True), ("G1 exploitation courante", g1.a, g1.b, False), ("G2 personnel", g2.a, g2.b, False), ("G3 structure", g3.a, g3.b, False)], SEUIL_VARIATION)
    tresorerie_et_alertes(cx, t, (emp.a.cum - pser(cx, ("68",)).a.cum) / cx.n)
    if cx.J1 is None:
        cx.vigil("blue", "Pas de FEC N-1 : variations N/N-1 non calculées.")
    anomalies_comptes(cx)
    onglets = [("Synthèse", h1), ("Tableau cumul", h2), ("Produits de la tarification", h3), ("Charges G1/G2/G3", h4), ("Charges externes", h5),
               ("Compte de résultat", h6), ("Indicateurs d'activité", h7), ("Trésorerie & BFR", ht), ("Scénarios", hsc), ("Points de vigilance", onglet_vigilance(cx))]
    notes = pied_notes(["ESMS : produits = classe 7, charges = classe 6 ; les % sont calculés sur le total des produits. Aucun budget autorisé n'est utilisé (non fourni).",
                        "HYPOTHÈSE À VALIDER : G1 = compte 60 ; G2 = comptes 64, 631, 633 ; G3 = comptes 61, 62, 63 (hors 631, 633), 65 à 69. Le cadre budgétaire normalisé de l'établissement peut ranger certains comptes autrement.",
                        "Les résultats par section tarifaire, le GMP/PMP et les ETP ne figurent pas dans le FEC : ils ne sont pas calculés."])
    return onglets, resume, notes
