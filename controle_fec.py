"""Controle de coherence d'un FEC : calcul deterministe en Python, le modele n'a qu'a commenter le resultat.

Le fichier reste sur le PC : il est lu localement par le serveur MCP, rien n'est envoye ailleurs.
"""
import collections
import csv
import datetime
import io
import glob
import os
import platform
import re
import unicodedata
from decimal import Decimal, InvalidOperation

ICI = os.path.dirname(os.path.abspath(__file__))
MAX_SORTIE = 4600   # ~1300 tokens : confortable pour le contexte de 64k d'Hermes
ZERO = Decimal("0")
CENT = Decimal("0.01")
REQUIS = ("journalcode", "ecriturenum", "ecrituredate", "comptenum", "debit", "credit")


# --------------------------------------------------------------------------- lecture

def montant(s):
    s = (s or "").strip().replace(" ", "").replace(" ", "")
    if not s:
        return ZERO
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"montant illisible : « {s} »")


def date_de(s):
    s = (s or "").strip()
    for fmt in ("%Y%m%d", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def jj(d):
    return d.strftime("%d/%m/%Y") if d else "?"


def eur(x):
    x = Decimal(x).quantize(CENT)
    s = f"{abs(x):,.2f}".replace(",", " ").replace(".", ",")
    return ("-" if x < 0 else "") + s + " €"


def lire_fec(chemin):
    if not os.path.isfile(chemin):
        dossier = os.path.dirname(chemin) or "."
        voisins = []
        if os.path.isdir(dossier):
            voisins = [f for f in sorted(os.listdir(dossier)) if f.lower().endswith((".txt", ".csv", ".fec"))][:12]
        raise ValueError(f"fichier introuvable : {chemin}." + (f" Fichiers proches : {', '.join(voisins)}" if voisins else ""))
    data = open(chemin, "rb").read()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        texte = data.decode("utf-16")
    else:
        try:
            texte = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            texte = data.decode("cp1252", errors="replace")
    premiere = texte.split("\n", 1)[0]
    sep = max(("\t", "|", ";"), key=premiere.count)
    lecteur = csv.reader(io.StringIO(texte), delimiter=sep)
    entete = next(lecteur, [])
    idx = {re.sub(r"[^a-z]", "", c.lower()): i for i, c in enumerate(entete)}
    manque = [c for c in REQUIS if c not in idx]
    if manque:
        raise ValueError("ce fichier ne ressemble pas a un FEC (colonnes absentes : " + ", ".join(manque) +
                         "). Colonnes trouvees : " + ", ".join(c.strip() for c in entete[:20]))

    def val(ligne, cle):
        i = idx.get(cle)
        return ligne[i].strip() if i is not None and i < len(ligne) else ""

    lignes, illisibles = [], 0
    for brut in lecteur:
        if not brut or not any(x.strip() for x in brut):
            continue
        try:
            lignes.append({
                "j": val(brut, "journalcode"), "jlib": val(brut, "journallib"), "n": val(brut, "ecriturenum"),
                "date": date_de(val(brut, "ecrituredate")), "cpt": val(brut, "comptenum"),
                "cptlib": val(brut, "comptelib"), "aux": val(brut, "compauxnum"),
                "piece": val(brut, "pieceref"), "lib": val(brut, "ecriturelib"),
                "d": montant(val(brut, "debit")), "c": montant(val(brut, "credit")),
                "let": val(brut, "ecriturelet"), "valid": val(brut, "validdate"),
                "auxlib": val(brut, "compauxlib"), "pdate": date_de(val(brut, "piecedate")),
                "dlet": date_de(val(brut, "datelet")),
            })
        except ValueError:
            illisibles += 1
    if not lignes:
        raise ValueError("aucune ecriture lisible dans ce fichier.")
    return lignes, illisibles



# --------------------------------------------------------------------------- controles propres a chaque type de dossier

TYPES_CONTROLES = {"bic": "BIC (SAS, SARL, EURL, EI)", "bnc": "BNC (professions liberales)", "sci_ir": "SCI a l'IR (revenus fonciers)",
                   "sci_is": "SCI a l'IS", "association": "association loi 1901", "esms": "association ESMS"}
AN_JOURNAUX = {"AN", "RAN", "A-N", "ANO", "ANOUV", "A NOUVEAU", "ANX", "RAN1"}


def est_an(l):
    """Ligne d'a-nouveaux : code de journal connu (AN, RAN...) ou libelle du journal « A NOUVEAU » (journal code 00, par exemple)."""
    if l["j"].strip().upper() in AN_JOURNAUX:
        return True
    lib = unicodedata.normalize("NFD", l.get("jlib") or "").encode("ascii", "ignore").decode().casefold()
    return "nouveau" in lib


CLOTURES = {"CLO", "CL", "CLOT", "CLOTURE", "CLÔTURE", "ODCL", "OD-CLO", "CLS"}


def controles_specifiques(typ, lignes):
    """Controles de coherence propres au type de dossier. Renvoie (constats, noms des controles executes).
    Regles verifiees : fonds dedies (19, 689, 789) et contributions volontaires en nature (86 = 87) : Associatheque ;
    amortissement non deductible des revenus fonciers en location nue, terrain non amortissable : source secondaire (swapn.fr), a confirmer au BOFiP."""
    if typ not in TYPES_CONTROLES:
        return [], []
    ex = [l for l in lignes if not (l["j"].upper() in CLOTURES and l["cpt"][:1] in ("6", "7"))]
    mv = [l for l in ex if not est_an(l)]

    def solde(pref, src=ex, excl=()):
        return sum((l["d"] - l["c"] for l in src if l["cpt"].startswith(pref) and not l["cpt"].startswith(excl)), ZERO)

    dates = [l["date"] for l in lignes if l["date"]]
    nb_mois = ((max(dates).year - min(dates).year) * 12 + max(dates).month - min(dates).month + 1) if dates else 0
    complet = nb_mois >= 11            # exercice (presque) complet : les controles « absence d'ecriture de fin d'exercice » ont un sens
    res, noms = [], []

    def ajoute(nom, texte):
        noms.append(nom)
        if texte:
            res.append("- " + texte)

    ca = -solde("70", mv)
    amort_ok = typ in ("bic", "bnc", "sci_is", "association", "esms")

    # --- compte courant d'associe debiteur (societes)
    if typ in ("bic", "sci_ir", "sci_is"):
        par_aux = collections.defaultdict(lambda: ZERO)
        for l in ex:
            if l["cpt"].startswith("455"):
                par_aux[l["aux"] or l["cpt"]] += l["d"] - l["c"]
        deb = sorted(((v, k) for k, v in par_aux.items() if v >= 1), reverse=True)
        ajoute("compte courant d'associe debiteur",
               f"compte courant d'associe (455) debiteur pour {eur(sum(v for v, _ in deb))} ({', '.join(f'{k} {eur(v)}' for v, k in deb[:2])}) : avance de la societe a un associe ou dirigeant, a justifier (remboursement, remuneration, interets)." if deb else "")

    # --- impot sur les benefices non comptabilise
    if typ in ("bic", "sci_is") and complet:
        r_avant_is = -solde(("6", "7"), ex) + solde("695", ex)
        if r_avant_is > 0 and abs(solde("695", mv)) < 1:
            ajoute("impot sur les societes", f"resultat avant impot beneficiaire de {eur(r_avant_is)} et aucun impot sur les societes (695) comptabilise sur l'exercice"
                   + (" (sans objet si l'entite est a l'IR)." if typ == "bic" else " : IS non passe ?"))
        else:
            ajoute("impot sur les societes", "")

    # --- immobilisations et amortissements
    if amort_ok:
        # regroupement par famille : 2154* <-> 28154*, 213* <-> 2813*, 205* <-> 2805*
        familles = collections.defaultdict(lambda: ZERO)
        for l in ex:
            c = l["cpt"]
            if c.startswith("205"):
                familles[c[:3]] += l["d"] - l["c"]
            elif c.startswith(("212", "213", "214", "215", "218")):
                familles[c[:4] if c.startswith(("215", "218")) else c[:3]] += l["d"] - l["c"]
        sur = []
        for fam, b in familles.items():
            a_ = -solde("28" + fam[1:], ex)
            if a_ - b > 1:
                sur.append((a_ - b, fam, b, a_))
        sur.sort(reverse=True)
        brut_tot = sum(familles.values(), ZERO)
        amort_tot = -solde("28", ex, excl=("2811",))
        txt = []
        if sur:
            txt.append(f"amortissements superieurs a la valeur brute sur {len(sur)} famille(s) d'immobilisations (ex. {sur[0][1]}* : brut {eur(sur[0][2])}, amortissements {eur(sur[0][3])}).")
        if complet and brut_tot >= 1 and amort_tot < brut_tot - 1 and abs(solde("681", mv)) < 1:
            txt.append(f"immobilisations amortissables de {eur(brut_tot)} (amorties a hauteur de {eur(amort_tot)}) mais aucune dotation aux amortissements (681) sur l'exercice : amortissements non passes ?")
        if typ in ("sci_is",):
            terrain = [l for l in ex if l["cpt"].startswith("281") and (l["cpt"].startswith("2811") or "TERRAIN" in l["cptlib"].upper())]
            tt = sum((l["c"] - l["d"] for l in terrain), ZERO)
            if abs(tt) >= 1:
                txt.append(f"amortissement porte sur un terrain ({eur(tt)}) : un terrain n'est en principe pas amortissable (seul l'immeuble l'est, par composants).")
        ajoute("immobilisations et amortissements", " ".join(txt))

    # --- BIC : ecritures d'inventaire, TVA collectee
    if typ == "bic" and complet:
        inv = [c for c in ("408", "418", "486", "487", "4486", "681", "686", "603", "39", "29", "15") if abs(solde(c, mv)) >= 1]
        ajoute("ecritures d'inventaire", "" if inv else "aucune ecriture d'inventaire detectee (ni factures non parvenues 408, ni charges constatees d'avance 486, ni dotations 681/686, ni variation de stock 603, ni depreciations) : FEC avant inventaire ?")
    if typ in ("bic", "bnc") and ca >= 1000:
        tva = -solde("4457", mv)
        if abs(tva) < 1:
            ajoute("TVA collectee", f"aucune TVA collectee (4457) pour {eur(ca)} de chiffre d'affaires : franchise en base ou TVA non comptabilisee ?")
        elif tva / ca * 100 > Decimal("20.5"):
            taux = f"{(tva / ca * 100):.1f}".replace(".", ",")
            ajoute("TVA collectee", f"TVA collectee {eur(tva)} = {taux} % du chiffre d'affaires, au-dessus du taux normal de 20 % : TVA sur d'autres produits (cessions...) ou chiffre d'affaires sous-evalue ?")
        else:
            ajoute("TVA collectee", "")

    # --- BNC : comptabilite de tresorerie
    if typ == "bnc":
        cl, fo = solde("411", ex), -solde("401", ex)
        ajoute("tiers en comptabilite de tresorerie",
               f"comptes de tiers non soldes (clients 411 : {eur(cl)} ; fournisseurs 401 : {eur(fo)}) : normal seulement en option creances-dettes ; en comptabilite de tresorerie, des recettes ou depenses non encaissees/decaissees seraient comptees a tort." if abs(cl) >= 1 or abs(fo) >= 1 else "")

    # --- SCI : revenus fonciers / IS
    if typ in ("sci_ir", "sci_is"):
        interets = solde("661", mv)
        cap = -sum((l["d"] for l in mv if l["cpt"].startswith("164")), ZERO)     # remboursements de capital = debits du 164
        ajoute("emprunt : capital et interets",
               f"interets d'emprunt (661) de {eur(interets)} mais aucun remboursement de capital (debit du 164) : l'annuite a-t-elle ete passee en totalite en charge ? (le capital rembourse n'est pas une charge)." if interets >= 1 and cap > -1 else "")
        immeuble = solde(("213", "214", "211"), ex)
        ajoute("taxe fonciere", "aucune taxe fonciere (63512) sur l'exercice alors que l'immeuble est a l'actif : verifier (autre compte, ou prise en charge par un tiers)." if complet and immeuble >= 1 and abs(solde("63512", mv)) < 1 else "")
    if typ == "sci_ir":
        dot = solde("68", mv)
        ajoute("amortissements en SCI a l'IR",
               f"dotations (68) de {eur(dot)} en SCI a l'IR : l'amortissement n'est en principe pas deductible des revenus fonciers (location nue) ; a retraiter sur la declaration, ou a verifier si l'activite est une location meublee (BIC)." if dot >= 1 else "")
        is_ = solde("695", mv)
        ajoute("IS en SCI a l'IR", f"impot sur les societes (695) de {eur(is_)} comptabilise dans une SCI declaree a l'IR : option pour l'IS non signalee ?" if abs(is_) >= 1 else "")

    # --- association / ESMS
    if typ in ("association", "esms"):
        v19 = -solde("19", mv)                       # variation du passif « fonds dedies »
        d689, c789 = solde("689", mv), -solde("789", mv)
        attendu = d689 - c789
        ajoute("fonds dedies", f"fonds dedies : variation du compte 19 {eur(v19)} contre dotations 689 moins utilisations 789 = {eur(attendu)} (ecart {eur(v19 - attendu)}) : la variation du 19 doit correspondre a 689 - 789."
               if (abs(v19) >= 1 or abs(d689) >= 1 or abs(c789) >= 1) and abs(v19 - attendu) >= 1 else "")
        e86, r87 = solde("86", ex), -solde("87", ex)
        ajoute("contributions volontaires en nature", f"contributions volontaires en nature : emplois (86) {eur(e86)} contre ressources (87) {eur(r87)} ; les deux totaux doivent etre egaux (ecart {eur(e86 - r87)})."
               if (abs(e86) >= 1 or abs(r87) >= 1) and abs(e86 - r87) >= 1 else "")
    return res, noms


# --------------------------------------------------------------------------- analyse

def cle_ecriture(l):
    return (l["j"], l["n"])


def nom_ecriture(cle):
    return f"{cle[0]}:{cle[1]}"


def detail_ecriture(lignes, ref):
    ref = ref.strip()
    if ":" in ref:
        j, n = ref.split(":", 1)
        sel = [l for l in lignes if l["j"].upper() == j.strip().upper() and l["n"] == n.strip()]
    else:
        sel = [l for l in lignes if l["n"] == ref or l["piece"] == ref]
    if not sel:
        return f"Ecriture « {ref} » introuvable (format attendu : JOURNAL:NUMERO, ex. VT:1234, ou le numero / la reference de piece)."
    cles = sorted({cle_ecriture(l) for l in sel})
    sorties = []
    for cle in cles[:3]:
        ls = [l for l in sel if cle_ecriture(l) == cle]
        d, c = sum(l["d"] for l in ls), sum(l["c"] for l in ls)
        dates = [l["date"] for l in ls if l["date"]]
        titre = f"Ecriture {nom_ecriture(cle)} : {len(ls)} lignes, du {jj(min(dates)) if dates else '?'} au {jj(max(dates)) if dates else '?'}, debit {eur(d)}, credit {eur(c)}, ecart {eur(d - c)}"
        corps = []
        for l in sorted(ls, key=lambda x: (x["date"] or datetime.date.min))[:22]:
            corps.append(f"  {jj(l['date'])} {l['cpt']:<9} {l['lib'][:28]:<28} D {eur(l['d']) if l['d'] else '-':>12} C {eur(l['c']) if l['c'] else '-':>12}")
        if len(ls) > 22:
            corps.append(f"  ... {len(ls) - 22} lignes de plus")
        sorties.append(titre + "\n" + "\n".join(corps))
    return "\n\n".join(sorties)[:MAX_SORTIE * 2]


def analyser(chemin, date_arrete=None, ecriture=None, debut=None, fin=None, type_dossier=None):
    lignes, illisibles = lire_fec(chemin)
    if ecriture:
        return detail_ecriture(lignes, ecriture)

    arrete, d0, d1 = date_de(date_arrete), date_de(debut), date_de(fin)
    if date_arrete and not arrete:
        raise ValueError(f"date d'arrete illisible : {date_arrete} (format JJ/MM/AAAA)")
    dates = [l["date"] for l in lignes if l["date"]]
    ecritures = collections.defaultdict(list)
    for l in lignes:
        ecritures[cle_ecriture(l)].append(l)
    tot_d = sum(l["d"] for l in lignes)
    tot_c = sum(l["c"] for l in lignes)

    out = [f"FEC {os.path.basename(chemin)} : {len(lignes)} lignes, {len(ecritures)} ecritures, du {jj(min(dates)) if dates else '?'} au {jj(max(dates)) if dates else '?'}.",
           f"Total : debit {eur(tot_d)}, credit {eur(tot_c)}, ecart {eur(tot_d - tot_c)}" + (" (equilibre)." if abs(tot_d - tot_c) < CENT else ".")]
    if illisibles:
        out.append(f"{illisibles} ligne(s) illisible(s) ignoree(s).")

    controles = ["equilibre global", "equilibre par ecriture"]

    # 1. Equilibre a une date d'arrete et ecritures « a cheval »
    cheval = []
    if arrete:
        controles.append("equilibre a la date d'arrete")
        av = [l for l in lignes if l["date"] and l["date"] <= arrete]
        d_a, c_a = sum(l["d"] for l in av), sum(l["c"] for l in av)
        out.append(f"A la date du {jj(arrete)} (lignes datees au plus tard ce jour) : debit {eur(d_a)}, credit {eur(c_a)}, ecart {eur(d_a - c_a)}.")
        cheval = []
        for cle, ls in ecritures.items():
            avant = [l for l in ls if l["date"] and l["date"] <= arrete]
            apres = [l for l in ls if not l["date"] or l["date"] > arrete]
            if avant and apres:
                ecart = sum(l["d"] - l["c"] for l in avant)
                if abs(ecart) >= CENT:
                    cheval.append((abs(ecart), cle, ecart, len(avant), len(apres), ls[0]["lib"], ls))
        cheval.sort(key=lambda x: x[0], reverse=True)
        if cheval:
            somme = sum(x[2] for x in cheval)
            out.append(f"{len(cheval)} ecriture(s) a cheval sur cette date (lignes avant ET apres) ; leurs ecarts partiels totalisent {eur(somme)}"
                       + (" = l'ecart ci-dessus." if abs(somme - (d_a - c_a)) < CENT else " (ecart ci-dessus : " + eur(d_a - c_a) + ")."))
            for _, cle, ecart, na, nb, lib, ls in cheval[:5]:
                dts = [l["date"] for l in ls if l["date"]]
                tot = sum(l["d"] - l["c"] for l in ls)
                etat = "ecriture equilibree au total" if abs(tot) < CENT else f"ECRITURE ELLE-MEME DESEQUILIBREE de {eur(tot)}"
                out.append(f"  - {nom_ecriture(cle)} « {lib[:30]} » : {na} ligne(s) avant, {nb} apres, ecart partiel {eur(ecart)} ; {etat} ; lignes datees du {jj(min(dts))} au {jj(max(dts))}")
            if abs(somme - (d_a - c_a)) < CENT and all(abs(sum(l["d"] - l["c"] for l in x[6])) < CENT for x in cheval):
                fin_max = max(l["date"] for x in cheval for l in x[6] if l["date"])
                un = len(cheval) == 1
                out.append(f"Conclusion : ce n'est pas une erreur de montant. {'Cette ecriture est equilibree' if un else 'Ces ecritures sont equilibrees'} au total, "
                           f"mais {'ses lignes portent' if un else 'leurs lignes portent'} des dates differentes (en principe une ecriture = une seule date) ; l'ecart disparait des le {jj(fin_max)}. "
                           "A corriger a la source en datant l'ecriture d'un seul jour, ou a signaler a l'editeur du logiciel.")
        elif abs(d_a - c_a) >= CENT:
            out.append("Aucune ecriture a cheval n'explique cet ecart : chercher une ecriture deja desequilibree ou une date manquante.")

    # 2. Ecritures desequilibrees
    desequilibrees = []
    for cle, ls in ecritures.items():
        e = sum(l["d"] - l["c"] for l in ls)
        if abs(e) >= CENT:
            desequilibrees.append((abs(e), cle, e, len(ls), ls[0]["lib"]))
    desequilibrees.sort(reverse=True)
    if desequilibrees:
        out.append(f"{len(desequilibrees)} ecriture(s) desequilibree(s) (somme debit <> somme credit) :")
        for _, cle, e, n, lib in desequilibrees[:5]:
            out.append(f"  - {nom_ecriture(cle)} « {lib[:30]} » : {n} lignes, ecart {eur(e)}")
    else:
        out.append("Toutes les ecritures sont equilibrees individuellement.")

    # 2bis. Controles propres au type de dossier
    typ = type_dossier if type_dossier in TYPES_CONTROLES else None
    if typ:
        constats, noms = controles_specifiques(typ, lignes)
        controles.append("controles propres au type " + TYPES_CONTROLES[typ] + " (" + ", ".join(noms) + ")")
        out.append(f"Controles propres au dossier {TYPES_CONTROLES[typ]} : " + ("" if constats else "aucune anomalie detectee."))
        out.extend(constats)
    else:
        out.append("Type de dossier non precise : controles propres au type (bic, bnc, sci_ir, sci_is, association, esms) non lances.")

    # 3. Ecritures a dates multiples
    out.append("Constats secondaires (ne les resumer qu'en une phrase, sauf si l'utilisateur les demande) :")
    controles.append("ecritures a dates multiples")
    deja = {x[1] for x in cheval}
    etalees = []
    for cle, ls in ecritures.items():
        ds = [l["date"] for l in ls if l["date"]]
        if ds and max(ds) > min(ds) and cle not in deja:
            etalees.append(((max(ds) - min(ds)).days, cle, len(ls), min(ds), max(ds), ls[0]["lib"]))
    etalees.sort(reverse=True)
    if etalees:
        out.append(f"{len(etalees)} {'autre(s) ' if deja else ''}ecriture(s) dont les lignes portent des dates differentes (sans effet sur les montants, mais fausse tout arrete en cours de periode) :")
        for jours, cle, n, a, b, lib in etalees[:3]:
            out.append(f"  - {nom_ecriture(cle)} « {lib[:30]} » : {n} lignes du {jj(a)} au {jj(b)}")

    # 4. Lignes anormales
    controles.append("lignes anormales")
    deux = [l for l in lignes if l["d"] and l["c"]]
    neg = [l for l in lignes if l["d"] < 0 or l["c"] < 0]
    nul = [l for l in lignes if not l["d"] and not l["c"]]
    sans_date = [l for l in lignes if not l["date"]]
    for libelle, liste in (("lignes avec debit ET credit", deux), ("lignes a montant negatif", neg),
                           ("lignes a montant nul", nul), ("lignes sans date lisible", sans_date)):
        if liste:
            ex = liste[0]
            out.append(f"{len(liste)} {libelle} (ex. {nom_ecriture(cle_ecriture(ex))} compte {ex['cpt']}).")

    # 5. Dates hors exercice
    if d0 or d1:
        controles.append("dates hors exercice")
        hors = [l for l in lignes if l["date"] and ((d0 and l["date"] < d0) or (d1 and l["date"] > d1))]
        if hors:
            ex = hors[0]
            out.append(f"{len(hors)} ligne(s) datee(s) hors exercice (ex. {nom_ecriture(cle_ecriture(ex))} le {jj(ex['date'])}).")

    # 6. Soldes de sens inhabituel (comptes normalement crediteurs / debiteurs ecartes : 603 et 71 variations de stock, 609/619/629 RRR,
    #    649 remboursements de charges de personnel, 699 credits d'impot, 709 RRR accordes)
    controles.append("soldes de sens inhabituel")
    soldes = collections.defaultdict(lambda: ZERO)
    libs = {}
    for l in lignes:
        soldes[l["cpt"]] += l["d"] - l["c"]
        libs.setdefault(l["cpt"], l["cptlib"])
    inhab = []
    for cpt, s in soldes.items():
        if abs(s) < CENT:
            continue
        if cpt.startswith(("411", "413", "416", "418")) and s < 0:
            inhab.append((abs(s), cpt, s, "client crediteur"))
        elif cpt.startswith(("401", "403", "408")) and s > 0:
            inhab.append((abs(s), cpt, s, "fournisseur debiteur"))
        elif cpt.startswith(("512", "53")) and s <= -1:
            inhab.append((abs(s), cpt, s, "tresorerie creditrice (decouvert ?)"))
        elif cpt.startswith("6") and s < 0 and not cpt.startswith(("603", "609", "619", "629", "649", "699")):
            inhab.append((abs(s), cpt, s, "charge crediteur" + (" ; souvent la reprise de la provision de conges payes N-1, normale avant l'inventaire" if cpt.startswith(("6412", "6458")) else "")))
        elif cpt.startswith("7") and s > 0 and not cpt.startswith(("709", "71")):
            inhab.append((abs(s), cpt, s, "produit debiteur"))
    inhab.sort(reverse=True)
    if inhab:
        out.append(f"{len(inhab)} compte(s) general(aux) au solde de sens inhabituel (a verifier, pas forcement faux) :")
        for _, cpt, s, motif in inhab[:4]:
            out.append(f"  - {cpt} {libs.get(cpt, '')[:22]} : {eur(s)} ({motif})")
    soldes_aux = collections.defaultdict(lambda: ZERO)
    for l in lignes:
        if l["aux"]:
            soldes_aux[(l["cpt"], l["aux"])] += l["d"] - l["c"]
    cli = sorted(((abs(s), c, a, s) for (c, a), s in soldes_aux.items() if c.startswith(("411", "413", "416", "418")) and s <= -CENT), reverse=True)
    fou = sorted(((abs(s), c, a, s) for (c, a), s in soldes_aux.items() if c.startswith(("401", "403", "408")) and s >= CENT), reverse=True)
    for nom, liste in (("client(s) crediteur(s)", cli), ("fournisseur(s) debiteur(s)", fou)):
        if liste:
            out.append(f"{len(liste)} tiers {nom} pour {eur(sum(x[0] for x in liste))} (frequent : acomptes, avoirs, reglements non affectes) ; plus gros : "
                       + ", ".join(f"{c}/{a} {eur(s)}" for _, c, a, s in liste[:2]) + ".")

    # 6bis. Comptes d'attente et de virements internes non soldes
    controles.append("comptes d'attente et virements internes")
    attente = sorted(((abs(v), c, v) for c, v in soldes.items() if c.startswith(("471", "472", "473", "58")) and abs(v) >= CENT), reverse=True)
    if attente:
        out.append(f"{len(attente)} compte(s) d'attente ou de virements internes non solde(s) (a solder en fin de periode) : "
                   + " ; ".join(f"{c} {libs.get(c, '')[:22]} {eur(v)}" for _, c, v in attente[:3]) + ".")

    # 7. Ecritures en double (meme journal, piece, date et memes lignes)
    controles.append("ecritures en double")
    signatures = collections.defaultdict(list)
    for cle, ls in ecritures.items():
        if any(l["d"] or l["c"] for l in ls):
            dts = [l["date"] for l in ls if l["date"]]
            sig = (cle[0], ls[0]["piece"], min(dts) if dts else None, tuple(sorted((l["cpt"], l["d"], l["c"]) for l in ls)))
            signatures[sig].append(cle)
    doublons = [(sig, cles) for sig, cles in signatures.items() if len(cles) > 1 and sig[1]]
    if doublons:
        doublons.sort(key=lambda x: -len(x[1]))
        out.append(f"{len(doublons)} groupe(s) d'ecritures identiques (meme journal, piece, date et lignes) :")
        for sig, cles in doublons[:3]:
            out.append(f"  - {', '.join(nom_ecriture(c) for c in cles[:4])} : piece {sig[1]} du {jj(sig[2])}")

    # 8. Lettrage : somme non nulle = lettrage partiel (plusieurs lignes) ou lettre sans contrepartie dans le fichier (une seule ligne)
    controles.append("lettrage")
    lettres = collections.defaultdict(lambda: [ZERO, 0])
    for l in lignes:
        if l["let"]:
            g = lettres[(l["cpt"], l["aux"], l["let"])]
            g[0] += l["d"] - l["c"]
            g[1] += 1
    partiels = sorted(((abs(g[0]), k, g[0]) for k, g in lettres.items() if abs(g[0]) >= CENT and g[1] >= 2), reverse=True)
    isoles = sorted(((abs(g[0]), k, g[0]) for k, g in lettres.items() if abs(g[0]) >= CENT and g[1] < 2), reverse=True)
    for liste, texte in ((partiels, "lettrage(s) partiel(s) (plusieurs lignes, somme non nulle : souvent un reglement partiel, reste a regler)"),
                         (isoles, "lettre(s) porte(s) par une seule ligne (contrepartie absente de la periode du fichier : a verifier)")):
        if liste:
            out.append(f"{len(liste)} {texte} pour {eur(sum(x[0] for x in liste))} ; plus gros : "
                       + ", ".join(f"{k[0]}/{k[1]} lettre {k[2]} {eur(s)}" for _, k, s in liste[:2]) + ".")

    # 9. Ecritures non validees
    nv = sum(1 for l in lignes if not l["valid"])
    if nv and nv < len(lignes):
        controles.append("validation")
        out.append(f"{nv} ligne(s) sans date de validation.")

    out.append("Controles effectues : " + ", ".join(controles) + ". Pour voir les lignes d'une ecriture : ecriture=\"JOURNAL:NUMERO\".")
    texte = "\n".join(out)
    return texte if len(texte) <= MAX_SORTIE else texte[:MAX_SORTIE].rsplit("\n", 1)[0] + "\n[... suite tronquee]"


# --------------------------------------------------------------------------- localisation des fichiers

EN_WSL = os.name != "nt" and ("microsoft" in platform.uname().release.lower() or bool(os.environ.get("WSL_DISTRO_NAME")))


def vers_posix(c):
    """Sous WSL : chemin Windows (C:\\... ou C:/...) -> /mnt/c/... ; sinon inchange."""
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", c or "")
    if m and EN_WSL:
        return "/mnt/" + m.group(1).lower() + "/" + m.group(2).replace("\\", "/")
    return c


def vers_affichage(p):
    """Sous WSL : /mnt/c/... -> C:\\... (lisible et ouvrable cote Windows) ; sinon inchange."""
    m = re.match(r"^/mnt/([a-z])/(.*)$", p or "")
    if m and EN_WSL:
        return m.group(1).upper() + ":\\" + m.group(2).replace("/", "\\")
    return p


def dossiers_de_recherche():
    home = os.path.expanduser("~")
    res = [os.path.join(ICI, "fec"), os.path.join(home, ".lmstudio", "scratchpads"),
           os.path.join(home, "Documents"), os.path.join(home, "Downloads"), os.path.join(home, "Desktop")]
    if EN_WSL:   # le ~ de WSL n'est pas celui de Windows : on ajoute les dossiers des profils Windows
        for profil in sorted(glob.glob("/mnt/c/Users/*")):
            if os.path.basename(profil).lower() in ("public", "default", "default user", "all users"):
                continue
            res += [os.path.join(profil, ".lmstudio", "scratchpads"), os.path.join(profil, "Documents"),
                    os.path.join(profil, "Downloads"), os.path.join(profil, "Desktop")]
    for extra in os.environ.get("FEC_DOSSIERS", "").split(os.pathsep):   # dossiers supplementaires (optionnel)
        if extra.strip():
            res.append(vers_posix(extra.strip()))
    return res


def parcourir(racine, profondeur=3):
    for dossier, sous, fichiers in os.walk(racine):
        if dossier[len(racine):].count(os.sep) >= profondeur:
            sous[:] = []
        for f in fichiers:
            yield dossier, f


def _cwd_config(texte):
    """Valeur de `terminal: cwd:` dans le texte d'un config.yaml de Hermes (sans dependance YAML)."""
    dans = False
    for ligne in texte.splitlines():
        if re.match(r"^terminal:\s*(#.*)?$", ligne):
            dans = True
            continue
        if dans:
            if ligne.strip() and not ligne[0].isspace() and not ligne.startswith("#"):
                break
            m = re.match(r"""^\s+cwd:\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|([^\s#]+))""", ligne)
            if m:
                if m.group(1) is not None:
                    return m.group(1).replace("\\\\", "\\")
                return m.group(2) if m.group(2) is not None else m.group(3)
    return None


def dossier_hermes():
    """Dossier de travail choisi dans Hermes (variable TERMINAL_CWD, sinon `terminal.cwd` de config.yaml) ; None si absent."""
    bruts = [os.environ.get("TERMINAL_CWD"), os.environ.get("HERMES_WORKSPACE")]
    homes = [os.environ.get("HERMES_HOME"), os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes"),
             os.path.join(os.path.expanduser("~"), "AppData", "Local", "hermes"), os.path.join(os.path.expanduser("~"), ".hermes")]
    for h in homes:
        f = os.path.join(h, "config.yaml") if h else ""
        if f and os.path.isfile(f):
            try:
                bruts.append(_cwd_config(open(f, encoding="utf-8", errors="replace").read()))
            except OSError:
                pass
            break
    for b in bruts:
        b = (b or "").strip()
        if b and b not in (".", "~"):
            d = vers_posix(os.path.expanduser(b))
            if os.path.isdir(d):
                return d
    return None


def resoudre_chemin(chemin):
    """Chemin saisi par le modele : guillemets, ~, ou simple nom de fichier (cherche dans les dossiers habituels,
    dont les pieces jointes de LM Studio / Bionic)."""
    c = vers_posix(os.path.expanduser(str(chemin or "").strip().strip('"').strip("'")))
    dh = dossier_hermes()
    for essai in ([os.path.join(dh, c)] if dh else []) + [c, os.path.join(ICI, "fec", c), os.path.join(ICI, c)]:
        if os.path.isfile(essai):
            return essai
    nom = os.path.basename(c.replace("\\", "/"))
    if not nom:
        return c
    for racines in ([[dh]] if dh else []) + [dossiers_de_recherche()]:   # d'abord le dossier choisi dans Hermes
        trouves = [os.path.join(d, f) for racine in racines if os.path.isdir(racine)
                   for d, f in parcourir(racine) if f == nom]
        if trouves:
            return max(trouves, key=os.path.getmtime)
    return c


def lister_fichiers():
    """Fichiers .txt / .csv / .fec recents dans les dossiers habituels (aide le modele a trouver le bon fichier)."""
    res = []
    for racine in dossiers_de_recherche():
        if not os.path.isdir(racine):
            continue
        for d, f in parcourir(racine, 2):
            if f.lower().endswith((".txt", ".csv", ".fec")):
                p = os.path.join(d, f)
                try:
                    res.append((os.path.getmtime(p), p, os.path.getsize(p)))
                except OSError:
                    pass
    res.sort(reverse=True)
    if not res:
        return "Aucun fichier .txt / .csv / .fec trouve. Depose le FEC dans le dossier « fec » du serveur ou donne son chemin complet."
    lignes = [f"{datetime.datetime.fromtimestamp(m):%d/%m/%Y %H:%M}  {t // 1024} Ko  {vers_affichage(p)}" for m, p, t in res[:15]]
    return "Fichiers recents (le plus recent d'abord) :\n" + "\n".join(lignes)
