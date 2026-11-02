# -*- coding: utf-8 -*-
"""Points en suspens d'un dossier, calcules sur le FEC : operations a justifier (comptes d'attente), factures clients
et fournisseurs non reglees depuis plus de N mois. Produit un mail de demande d'information (texte + fichier HTML a
copier dans Outlook). Calcul exact en Python (Decimal) : le modele ne fait que restituer le mail."""
import calendar
import datetime
import html
import os
import re
import unicodedata
import zipfile
from decimal import Decimal

import controle_fec as cf

ICI = os.path.dirname(os.path.abspath(__file__))
ZERO = Decimal("0")
CLIENTS = ("411", "413", "416")
FOURNISSEURS = ("401", "404")
ATTENTE = ("471", "472", "473")
MAX_TEXTE = 20     # lignes par rubrique dans le texte renvoye au modele
MAX_HTML = 300     # lignes par rubrique dans le fichier HTML


def cle_alpha(nom):
    """Cle de tri alphabetique : sans accents, sans casse, sans signes."""
    s = unicodedata.normalize("NFD", str(nom or "")).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", s).strip(), str(nom or "")


def moins_mois(d, n):
    m = d.month - 1 - n
    a = d.year + m // 12
    m = m % 12 + 1
    return datetime.date(a, m, min(d.day, calendar.monthrange(a, m)[1]))


def est_ouverte(l, arrete, explicite=False):
    """Ligne non lettree. Une ligne lettree est rapprochee quelle que soit la date de lettrage ; seule une date d'arret
    donnee par l'utilisateur (explicite) fait compter comme ouverte une ligne lettree apres cette date."""
    if l["date"] and l["date"] > arrete:
        return False
    if not l["let"]:
        return True
    return bool(explicite and l.get("dlet") and l["dlet"] > arrete)


def date_age(l, arrete):
    """Date de reference d'une ligne : la plus ancienne de la date d'ecriture et de la date de piece."""
    d, pd = l["date"] or arrete, l.get("pdate")
    return pd if pd and pd < d else d


MOYENS = re.compile(r"\b(?:cb|c b|cartes? (?:bleue?s?|bancaires?)|especes?|cheques?|caisse)\b")


DIVERS = re.compile(r"\bdivers\b")


def sans_tiers(l):
    """Ligne client sans compte auxiliaire propre (compte 411 seul) : on ne sait pas a quel client la rattacher."""
    return not l["aux"] or l["aux"] == l["cpt"]


def compte_special(l):
    """Compte client qui n'est pas un vrai client : compte 411 ou auxiliaire « especes », « CB », « carte bleue », « cheques »,
    « caisse » (libelle ou code du compte general, libelle ou code de l'auxiliaire), ou « clients divers » (fourre-tout, faute
    d'information). « Divers » n'est lu sur le compte general que s'il n'y a pas d'auxiliaire : un compte collectif « clients
    divers » regroupant de vrais clients ne doit pas tout ecarter."""
    general = cle_alpha(l["cpt"] + " " + l["cptlib"])[0]
    aux = cle_alpha(l.get("auxlib") or l["aux"])[0]
    return bool(MOYENS.search(general) or MOYENS.search(aux) or DIVERS.search(aux) or (sans_tiers(l) and DIVERS.search(general)))


def ecritures_banque(lignes):
    """Ecritures passees en banque ou en caisse : celles qui comportent une ligne sur un compte 51 ou 53 (hors a-nouveaux).
    Renvoie (ensemble des cles d'ecriture, codes des journaux concernes)."""
    cles, journaux = set(), set()
    for l in lignes:
        if l["cpt"].startswith(("51", "53")) and l["j"].strip().upper() not in cf.AN_JOURNAUX:
            cles.add(cf.cle_ecriture(l))
            journaux.add(l["j"])
    return cles, journaux


def _par_tiers(dic, debut, sans):
    out = []
    for t in dic.values():
        t["l"].sort(key=lambda x: (x[0], str(x[3] or "")))
        out.append({"nom": t["nom"], "nb": len(t["l"]), "montant": sum((x[2] for x in t["l"]), ZERO),
                    "lignes": [(("avant le " + cf.jj(debut)) if x[1] else cf.jj(x[0]), x[3] or sans, x[2]) for x in t["l"]]})
    out.sort(key=lambda x: cle_alpha(x["nom"]))
    return out


def points_tiers(lignes, prefixes, sens, arrete, limite, debut, mini, banque, reglements_toute_date=False, explicite=False, clients=False):
    """Ecritures NON LETTREES des comptes de tiers (le lettrage du FEC fait foi, aucune imputation par solde).
    Renvoie (factures, reglements, autres, partiels, info) :
      factures   : lignes du sens normal du tiers (debit client, credit fournisseur) plus anciennes que `limite` ;
      reglements : lignes de sens inverse d'une ecriture de banque ou de caisse (toutes dates si
                   `reglements_toute_date`, sinon plus anciennes que `limite`) ;
      autres     : total des autres lignes de sens inverse non lettrees (avoirs, OD) ;
      partiels   : (nombre, montant) de groupes lettres dont le solde n'est pas nul (lettrage partiel) ;
      info       : a-nouveaux non lettres ecartes (an), lignes sans compte auxiliaire (sans_aux), tiers ecartes
                   (exclus), nombre de tiers (nb_tiers) et motif si le cote client est ignore (ignore).
    Les a-nouveaux sont toujours ecartes (anciennete inconnue). Cote clients (`clients`) : lignes sans compte auxiliaire et
    comptes « especes », « CB », « cheques », « caisse » ecartes ; un seul client ou aucun = pas de suivi par tiers, tout est ignore."""
    opp = "c" if sens == "d" else "d"
    fact, regl, groupes, tiers = {}, {}, {}, set()
    autres = ZERO
    info = {"an": [0, ZERO], "sans_aux": 0, "exclus": set(), "nb_tiers": 0, "ignore": ""}
    for l in lignes:
        if not l["cpt"].startswith(prefixes) or (l["date"] and l["date"] > arrete):
            continue
        nom = l.get("auxlib") or l["cptlib"] or l["aux"] or l["cpt"]
        if clients:
            if compte_special(l):
                info["exclus"].add(l.get("auxlib") or l["cptlib"] or l["aux"] or l["cpt"])
                continue
            if sans_tiers(l):
                info["sans_aux"] += 1
                continue
            tiers.add(l["aux"])
        m = l[sens] - l[opp]
        cle = l["aux"] or l["cpt"]
        if l["let"] and not est_ouverte(l, arrete, explicite):
            groupes[(cle, l["let"])] = groupes.get((cle, l["let"]), ZERO) + m
            continue
        if m == 0:
            continue
        if l["j"].strip().upper() in cf.AN_JOURNAUX:
            info["an"][0] += 1
            info["an"][1] += abs(m)
            continue
        if m > 0:
            d = date_age(l, arrete)
            if d < limite and m >= mini:
                fact.setdefault(cle, {"nom": nom, "l": []})["l"].append((d, False, m, l["piece"] or l["lib"]))
        elif cf.cle_ecriture(l) in banque:
            d = l["date"] or arrete
            if (reglements_toute_date or d < limite) and -m >= mini:
                regl.setdefault(cle, {"nom": nom, "l": []})["l"].append((d, False, -m, l["lib"] or l["piece"]))
        else:
            autres += -m
    info["nb_tiers"] = len(tiers)
    if clients and len(tiers) <= 1:
        info["ignore"] = "aucun compte client détaillé par tiers" if not tiers else "un seul compte client"
        fact, regl = {}, {}
    ecarts = [abs(v) for v in groupes.values() if v != 0]
    return (_par_tiers(fact, debut, "(sans référence)"), _par_tiers(regl, debut, "(sans libellé)"), autres,
            (len(ecarts), sum(ecarts, ZERO)), info)


def operations_a_justifier(lignes, arrete, explicite=False):
    res = []
    for l in lignes:
        if l["cpt"].startswith(ATTENTE) and est_ouverte(l, arrete, explicite):
            m = l["d"] - l["c"]
            if m != 0:
                res.append({"date": l["date"], "lib": l["lib"] or l["piece"], "sens": "Paiement" if m > 0 else "Encaissement",
                            "montant": abs(m)})
    res.sort(key=lambda x: (x["date"] or datetime.date.min, x["lib"]))
    return res


# --------------------------------------------------------------------------- mise en forme

def _cell(s, n=44):
    s = str(s).replace("|", "/").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _pl(n, mot):
    return f"{n} {mot}{'s' if n > 1 else ''}"


def rubriques(ops, clients, fournisseurs, mois, sf_clients=(), sf_fournisseurs=()):
    r = []
    if ops:
        r.append({"titre": f"Justificatifs manquants pour des opérations bancaires ({_pl(len(ops), 'opération')}, {cf.eur(sum((o['montant'] for o in ops), ZERO))})",
                  "intro": "Nous n'avons pas pu rattacher les opérations bancaires suivantes à une facture ou à un justificatif :",
                  "cols": ["Date", "Libellé", "Sens", "Montant"],
                  "lignes": [[cf.jj(o["date"]), _cell(o["lib"]), o["sens"], cf.eur(o["montant"])] for o in ops],
                  "nums": [o["montant"] for o in ops], "feuille": "Justificatifs manquants",
                  "fin": "Pourriez-vous nous transmettre les pièces correspondantes (facture, note de frais, contrat…) ou, à défaut, nous préciser la nature de ces opérations ?"})
    for titre, items, intro, fin, nom, feuille in (
            (f"Factures clients sans règlement depuis plus de {mois} mois", clients,
             f"Nous n'avons pas pu rapprocher de règlement des factures clients suivantes, émises il y a plus de {mois} mois :",
             "Pour chacune, pourriez-vous nous dire si elle est toujours due (et si une relance est en cours), si elle a déjà été réglée (date et mode de règlement), si elle est contestée, ou si vous la considérez comme irrécouvrable ?",
             "Client", "Factures clients"),
            (f"Factures fournisseurs non réglées depuis plus de {mois} mois", fournisseurs,
             f"Nous n'avons pas pu rapprocher de règlement des factures fournisseurs suivantes, datées de plus de {mois} mois :",
             "Pourriez-vous nous confirmer qu'elles restent à régler, ou nous indiquer la date et le mode de règlement si elles ont déjà été payées ? Si l'une d'elles est contestée ou doit donner lieu à un avoir, merci de nous le préciser.",
             "Fournisseur", "Factures fournisseurs")):
        if items:
            lignes = [[_cell(x["nom"]), _cell(ref, 40), d, cf.eur(m)] for x in items for d, ref, m in x["lignes"]]
            r.append({"titre": f"{titre} ({_pl(len(lignes), 'facture')}, {cf.eur(sum((x['montant'] for x in items), ZERO))})",
                      "intro": intro, "cols": [nom, "N° de facture", "Date", "Montant"], "lignes": lignes, "fin": fin,
                      "nums": [m for x in items for _, _, m in x["lignes"]], "feuille": feuille})
    for titre, items, intro, fin, nom, feuille in (
            (f"Règlements de clients sans facture correspondante, de plus de {mois} mois", sf_clients,
             f"Nous n'avons pas pu rattacher à une facture de vente les encaissements suivants, enregistrés il y a plus de {mois} mois :",
             "Pourriez-vous nous indiquer à quelle facture ils se rapportent ou, si cette facture n'est pas dans nos écritures, nous en transmettre une copie ? S'il s'agit d'un acompte, d'un remboursement ou d'un avoir, merci de nous le préciser.",
             "Client", "Règlements clients"),
            ("Règlements de fournisseurs sans facture correspondante", sf_fournisseurs,
             "Nous n'avons pas pu rattacher à une facture d'achat les règlements suivants, quelle que soit leur date :",
             "Pourriez-vous nous transmettre les factures correspondantes ou, s'il s'agit d'un acompte, d'un remboursement ou d'un avoir, nous le préciser ?",
             "Fournisseur", "Règlements fournisseurs")):
        if items:
            lignes = [[_cell(x["nom"]), d, _cell(lib, 40), cf.eur(m)] for x in items for d, lib, m in x["lignes"]]
            r.append({"titre": f"{titre} ({_pl(len(lignes), 'règlement')}, {cf.eur(sum((x['montant'] for x in items), ZERO))})",
                      "intro": intro, "cols": [nom, "Date", "Libellé", "Montant"], "lignes": lignes, "fin": fin,
                      "nums": [m for x in items for _, _, m in x["lignes"]], "feuille": feuille})
    return r


def intro_mail(arrete):
    return (f"Nous espérons que vous allez bien. Pour finaliser votre comptabilité arrêtée au {cf.jj(arrete)}, "
            "il nous manque quelques éléments, que nous détaillons ci-dessous.")


def cloture(delai):
    return (f"Nous vous remercions par avance pour votre aide et vous serions reconnaissants de nous répondre d'ici le {delai}. "
            "Nous restons bien sûr à votre disposition si vous préférez que nous en parlions par téléphone.")


def mail_texte(rub, objet, salut, delai, signataire, intro):
    out = [f"Objet : {objet}", "", salut, "", intro, ""]
    for i, s in enumerate(rub, 1):
        out += [f"{i}. {s['titre']}", s["intro"], "", "| " + " | ".join(s["cols"]) + " |", "|" + "---|" * len(s["cols"])]
        for l in s["lignes"][:MAX_TEXTE]:
            out.append("| " + " | ".join(l) + " |")
        if len(s["lignes"]) > MAX_TEXTE:
            out.append(f"(… et {len(s['lignes']) - MAX_TEXTE} autre(s) ligne(s) : liste complète dans le fichier HTML)")
        out += ["", s["fin"], ""]
    out += [cloture(delai), "", "Bien cordialement,", signataire]
    return "\n".join(out)


def mail_html(rub, objet, salut, delai, signataire, intro):
    e = html.escape
    p = ['<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>' + e(objet) + '</title></head>'
         '<body style="font-family:Calibri,Arial,sans-serif;font-size:11pt;max-width:900px;margin:24px auto">',
         '<p style="color:#666;font-size:9pt;user-select:none;-webkit-user-select:none">Sélectionnez tout (Ctrl+A), copiez (Ctrl+C) et collez dans un nouveau message Outlook. '
         'Relisez avant envoi.</p>',
         f"<p><b>Objet : {e(objet)}</b></p>", f"<p>{e(salut)}</p>",
         f"<p>{e(intro)}</p>"]
    for i, s in enumerate(rub, 1):
        p.append(f"<p><b>{i}. {e(s['titre'])}</b><br>{e(s['intro'])}</p>")
        p.append('<table style="border-collapse:collapse;font-size:10pt"><tr>' + "".join(
            f'<th style="border:1px solid #999;padding:3px 8px;background:#eee;text-align:left">{e(c)}</th>' for c in s["cols"]) + "</tr>")
        for l in s["lignes"][:MAX_HTML]:
            p.append("<tr>" + "".join(f'<td style="border:1px solid #999;padding:3px 8px">{e(c)}</td>' for c in l) + "</tr>")
        p.append("</table>")
        if len(s["lignes"]) > MAX_HTML:
            p.append(f"<p><i>… et {len(s['lignes']) - MAX_HTML} autre(s) ligne(s) non reprises ici.</i></p>")
        p.append(f"<p>{e(s['fin'])}</p>")
    p.append(f"<p>{e(cloture(delai))}</p><p>Bien cordialement,<br>{e(signataire)}</p></body></html>")
    return "".join(p)


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _x(s):
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(s))
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _feuille_xml(rows, largeurs):
    """rows : liste de lignes ; cellule = texte, Decimal (montant) ou (texte, style) ; styles : 1 en-tete, 2 montant, 3 gras, 4 montant gras."""
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    out.append('<sheetViews><sheetView workbookViewId="0">' + ('<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>' if len(rows) > 1 else '') + '</sheetView></sheetViews>')
    out.append("<cols>" + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(largeurs)) + "</cols><sheetData>")
    for n, ligne in enumerate(rows, 1):
        out.append(f'<row r="{n}">')
        for j, c in enumerate(ligne):
            ref = f"{_col(j)}{n}"
            style = 0
            if isinstance(c, tuple):
                c, style = c
            if isinstance(c, Decimal):
                out.append(f'<c r="{ref}" s="{style or 2}"><v>{c}</v></c>')
            elif c in ("", None):
                continue
            else:
                out.append(f'<c r="{ref}" t="inlineStr"' + (f' s="{style}"' if style else "") + f'><is><t xml:space="preserve">{_x(c)}</t></is></c>')
        out.append("</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out)


def ecrire_xlsx(chemin, rub, objet):
    """Classeur Excel (sans bibliotheque externe) : une feuille de synthese puis une feuille par rubrique."""
    feuilles = []
    synth = [[(objet, 3)], [], [("Rubrique", 1), ("Nombre de lignes", 1), ("Montant", 1)]]
    for s in rub:
        synth.append([s["feuille"], str(len(s["lignes"])), sum(s["nums"], ZERO)])
    feuilles.append(("Synthèse", synth, [34, 18, 16]))
    for s in rub:
        rows = [[(c, 1) for c in s["cols"]]]
        for ligne, m in zip(s["lignes"], s["nums"]):
            rows.append(list(ligne[:-1]) + [m])
        rows.append(["Total"] + [""] * (len(s["cols"]) - 2) + [(sum(s["nums"], ZERO), 4)])
        rows[-1][0] = ("Total", 3)
        feuilles.append((s["feuille"], rows, [34, 40, 22, 16] if len(s["cols"]) == 4 else [24] * len(s["cols"])))
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                    for i in range(1, len(feuilles) + 1)) + "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join(f'<sheet name="{_x(nom)[:31]}" sheetId="{i}" r:id="rId{i}"/>' for i, (nom, _, _) in enumerate(feuilles, 1)) + "</sheets></workbook>")
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                        for i in range(1, len(feuilles) + 1))
              + f'<Relationship Id="rId{len(feuilles) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00\\ &quot;€&quot;"/></numFmts>'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFEEEEEE"/></patternFill></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
              '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
              '<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wbrels)
        z.writestr("xl/styles.xml", styles)
        for i, (_, rows, larg) in enumerate(feuilles, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _feuille_xml(rows, larg))


def generer(chemin, date_arrete=None, mois=3, nom_client=None, destinataire=None, signataire=None, delai=None, montant_min=10, afficher_mail=False, format_sortie=None):   # format_sortie : ignore, conserve pour compatibilite
    lignes, illisibles = cf.lire_fec(chemin)
    dates = [l["date"] for l in lignes if l["date"]]
    debut, fin = min(dates), max(dates)
    arrete = fin
    if date_arrete:
        arrete = cf.date_de(str(date_arrete))
        if not arrete:
            raise ValueError(f"date d'arret illisible : {date_arrete} (format JJ/MM/AAAA)")
    mois = int(mois) if str(mois or "").strip().isdigit() and int(mois) > 0 else 3
    limite = moins_mois(arrete, mois)
    explicite = bool(date_arrete)
    ops = operations_a_justifier(lignes, arrete, explicite)
    try:
        mini = Decimal(str(montant_min).replace(",", ".")) if str(montant_min or "").strip() else Decimal("10")
    except Exception:  # noqa: BLE001
        mini = Decimal("10")
    banque, journaux_b = ecritures_banque(lignes)
    clients, sf_c, au_c, pa_c, inf_c = points_tiers(lignes, CLIENTS, "d", arrete, limite, debut, mini, banque, False, explicite, True)
    fourn, sf_f, au_f, pa_f, inf_f = points_tiers(lignes, FOURNISSEURS, "c", arrete, limite, debut, mini, banque, True, explicite)
    rub = rubriques(ops, clients, fourn, mois, sf_c, sf_f)
    if not rub:
        return (f"Aucun point en suspens au {cf.jj(arrete)} : pas d'opération en compte d'attente (471-473), aucune facture "
                f"client ou fournisseur non réglée et aucun règlement sans facture depuis plus de {mois} mois."
                + (f" Clients non contrôlés ({inf_c['ignore']})." if inf_c["ignore"] else "")), None
    objet = f"Points en suspens au {cf.jj(arrete)}" + (f" – {nom_client}" if nom_client else "")
    salut = f"Bonjour {destinataire}," if destinataire else "Bonjour,"
    delai = delai or "[date limite]"
    signataire = signataire or "[Votre nom]"
    intro = intro_mail(arrete)
    texte = mail_texte(rub, objet, salut, delai, signataire, intro)
    base = "points_en_suspens_" + "".join(c if c.isalnum() else "_" for c in (nom_client or "dossier"))[:30] + f"_{arrete:%Y%m%d}"
    sortie = sortie_x = None
    for dossier in (cf.dossier_hermes(), os.path.join(ICI, "sorties")):   # d'abord le dossier choisi dans Hermes
        if not dossier:
            continue
        try:
            os.makedirs(dossier, exist_ok=True)
            sortie = os.path.join(dossier, base + ".html")
            sortie_x = os.path.join(dossier, base + ".xlsx")
            with open(sortie, "w", encoding="utf-8") as f:
                f.write(mail_html(rub, objet, salut, delai, signataire, intro))
            ecrire_xlsx(sortie_x, rub, objet)
            break
        except OSError:
            sortie = sortie_x = None
    if not sortie:
        raise ValueError("impossible d'ecrire le fichier du mail (dossier de travail Hermes et dossier « sorties » inaccessibles).")
    notes = [f"Base : FEC du {cf.jj(debut)} au {cf.jj(fin)}, état au {cf.jj(arrete)} ; sont repris les écritures NON LETTRÉES du FEC "
             + ("(lettrées après la date d'arrêté comprises) " if explicite else "(quelle que soit la date de lettrage) ")
             + f"; factures : ancienneté = date de la pièce, seuil {mois} mois (avant le {cf.jj(limite)}) ; "
             f"règlements = lignes des écritures de banque ou de caisse (comptes 51 et 53 ; journaux : {', '.join(sorted(journaux_b)) or 'aucun'}) ; "
             f"à-nouveaux et lignes inférieures à {cf.eur(mini)} ignorés ; opérations à justifier = comptes 471 à 473 non lettrés."]
    if inf_c["ignore"]:
        notes.append(f"Clients non contrôlés : {inf_c['ignore']} (pas de suivi par client dans ce dossier).")
    if inf_c["exclus"]:
        notes.append("Comptes clients écartés (espèces, CB, chèques, caisse, clients divers) : " + ", ".join(sorted(inf_c["exclus"], key=cle_alpha)[:12]) + ".")
    if inf_c["sans_aux"]:
        notes.append(f"{_pl(inf_c['sans_aux'], 'ligne')} sur le compte client général (411 sans compte auxiliaire) non reprise(s).")
    doubles_c = {x["nom"] for x in clients} & {x["nom"] for x in sf_c}
    doubles_f = {x["nom"] for x in fourn} & {x["nom"] for x in sf_f}
    if doubles_c or doubles_f:
        notes.append(f"À lettrer en interne avant envoi : {_pl(len(doubles_c), 'client')} et {_pl(len(doubles_f), 'fournisseur')} ont à la fois des factures et des règlements non lettrés repris ci-dessus.")
    if au_c or au_f:
        notes.append(f"Avoirs et OD de sens inverse non lettrés, hors écritures de banque, non repris : clients {cf.eur(au_c)}, fournisseurs {cf.eur(au_f)}.")
    if pa_c[0] or pa_f[0]:
        notes.append(f"Lettrages partiels non repris (groupes lettrés dont le solde n'est pas nul) : clients {pa_c[0]} groupe(s) / {cf.eur(pa_c[1])}, "
                     f"fournisseurs {pa_f[0]} groupe(s) / {cf.eur(pa_f[1])}.")
    if inf_c["an"][0] or inf_f["an"][0]:
        notes.append(f"À-nouveaux non lettrés non repris (trop anciens) : clients {_pl(inf_c['an'][0], 'ligne')} / {cf.eur(inf_c['an'][1])}, "
                     f"fournisseurs {_pl(inf_f['an'][0], 'ligne')} / {cf.eur(inf_f['an'][1])}.")
    if illisibles:
        notes.append(f"({illisibles} ligne(s) du FEC illisible(s), ignorée(s).)")
    notes.append(f"Mail complet à copier dans Outlook (à ouvrir dans le navigateur) : {cf.vers_affichage(sortie)}")
    notes.append(f"Classeur Excel avec les mêmes listes (une feuille par rubrique) : {cf.vers_affichage(sortie_x)}")
    if afficher_mail:
        notes.append("Restitue ce mail tel quel : ne modifie aucun montant ni aucun nom, ne l'envoie pas ; l'utilisateur le relit puis l'envoie.")
        return texte + "\n\n---\n" + "\n".join(notes), sortie
    resume = [f"Mail de points en suspens prêt (arrêté au {cf.jj(arrete)}) :"]
    if ops:
        resume.append(f"- Justificatifs manquants : {_pl(len(ops), 'opération')} à justifier, {cf.eur(sum((o['montant'] for o in ops), ZERO))}.")
    if inf_c["ignore"]:
        resume.append(f"- Clients non contrôlés ({inf_c['ignore']}).")
    for nom_r, items, tiers, mot, delai_r in (("Factures clients sans règlement", clients, "client", "facture", f" depuis plus de {mois} mois"),
                                              ("Factures fournisseurs non réglées", fourn, "fournisseur", "facture", f" depuis plus de {mois} mois"),
                                              ("Règlements de clients sans facture", sf_c, "client", "règlement", f" depuis plus de {mois} mois"),
                                              ("Règlements de fournisseurs sans facture", sf_f, "fournisseur", "règlement", " (toutes dates)")):
        if items:
            n = sum(len(x["lignes"]) for x in items)
            resume.append(f"- {nom_r}{delai_r} : {_pl(n, mot)} ({_pl(len(items), tiers)}), "
                          f"{cf.eur(sum((x['montant'] for x in items), ZERO))}.")
    consigne = ("Réponds en 3 ou 4 lignes : reprends ce résumé, indique les deux fichiers (mail HTML, classeur Excel) et, s'il y en a, la mention « à vérifier en interne » si elle figure dans les notes. "
                "NE recopie PAS le contenu et n'écris aucun tableau : tout est dans les fichiers. Le classeur Excel EXISTE DEJA : n'en crée pas toi-même, ne lis pas le HTML. Ne l'envoie pas. "
                "Si l'utilisateur veut lire le mail dans la conversation, relance l'outil avec afficher_mail=oui.")
    return "\n".join(resume) + "\n\n---\n" + "\n".join(notes) + "\n" + consigne, sortie
