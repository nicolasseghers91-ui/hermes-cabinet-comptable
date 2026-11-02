# -*- coding: utf-8 -*-
"""Points en suspens d'un dossier, calcules sur le FEC : operations a justifier (comptes d'attente), factures clients
et fournisseurs non reglees depuis plus de N mois. Produit un mail de demande d'information (texte + fichier HTML a
copier dans Outlook). Calcul exact en Python (Decimal) : le modele ne fait que restituer le mail."""
import calendar
import datetime
import html
import os
import re
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


def moins_mois(d, n):
    m = d.month - 1 - n
    a = d.year + m // 12
    m = m % 12 + 1
    return datetime.date(a, m, min(d.day, calendar.monthrange(a, m)[1]))


def est_ouverte(l, arrete):
    """Ligne non lettree a la date d'arret (ou lettree seulement apres cette date)."""
    if l["date"] and l["date"] > arrete:
        return False
    if not l["let"]:
        return True
    return bool(l.get("dlet") and l["dlet"] > arrete)


def date_age(l, debut, arrete):
    """(date de reference, reporte) ; reporte = report a nouveau, date d'origine inconnue (anterieure au debut d'exercice)."""
    if l["j"].strip().upper() in cf.AN_JOURNAUX:
        return debut - datetime.timedelta(days=1), True
    d, pd = l["date"] or arrete, l.get("pdate")
    if pd and pd < d:
        d = pd
    return d, False


def tiers_en_retard(lignes, prefixes, sens, arrete, limite, debut, mini=ZERO, sf_toute_date=False):
    """Factures de tiers restant a regler et plus anciennes que `limite`. Les reglements / avoirs non affectes sont
    imputes sur les factures les plus anciennes (les reglements les plus anciens d'abord). Renvoie (liste de tiers,
    reglements non affectes (nom, total), factures reportees recentes, reglements sans facture plus anciens que `limite`
    ou, avec `sf_toute_date`, de toutes dates)."""
    opp = "c" if sens == "d" else "d"
    par = {}
    for l in lignes:
        if not l["cpt"].startswith(prefixes) or not est_ouverte(l, arrete):
            continue
        cle = l["aux"] or l["cpt"]
        t = par.setdefault(cle, {"nom": l.get("auxlib") or l["cptlib"] or cle, "fact": [], "cred": []})
        m = l[sens] - l[opp]
        d, rep = date_age(l, debut, arrete)
        if m > 0:
            t["fact"].append((d, rep, m, l["piece"] or l["lib"]))
        elif m < 0:
            t["cred"].append([d, rep, -m, l["lib"] or l["piece"]])
    res, non_affectes, indetermine, sans_facture = [], [], ZERO, []
    for t in par.values():
        pile = sorted(t["cred"], key=lambda x: x[0])
        vivantes = []
        for d, rep, m, piece in sorted(t["fact"], key=lambda x: x[0]):
            while m > 0 and pile:
                imp = min(m, pile[0][2])
                pile[0][2] -= imp
                m -= imp
                if pile[0][2] == 0:
                    pile.pop(0)
            if m > 0:
                vivantes.append((d, rep, m, piece))
        if pile:
            non_affectes.append((t["nom"], sum((x[2] for x in pile), ZERO)))
            vieux = [x for x in pile if (sf_toute_date or x[0] < limite) and x[2] >= mini]
            if vieux:
                sans_facture.append({"nom": t["nom"], "nb": len(vieux), "montant": sum((x[2] for x in vieux), ZERO),
                                     "lignes": [(("avant le " + cf.jj(debut)) if x[1] else cf.jj(x[0]), x[3] or "(sans libellé)", x[2])
                                                for x in vieux]})
        anciennes = [x for x in vivantes if x[0] < limite and x[2] >= mini]
        indetermine += sum((x[2] for x in vivantes if x[1] and x[0] >= limite), ZERO)
        if anciennes:
            res.append({"nom": t["nom"], "nb": len(anciennes), "montant": sum((x[2] for x in anciennes), ZERO),
                        "lignes": [(("avant le " + cf.jj(debut)) if x[1] else cf.jj(x[0]), x[3] or "(sans référence)", x[2])
                                   for x in anciennes]})
    res.sort(key=lambda x: -x["montant"])
    sans_facture.sort(key=lambda x: -x["montant"])
    return res, non_affectes, indetermine, sans_facture


def operations_a_justifier(lignes, arrete):
    res = []
    for l in lignes:
        if l["cpt"].startswith(ATTENTE) and est_ouverte(l, arrete):
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
             f"Nous n'avons trouvé aucun règlement pour les factures clients suivantes, émises il y a plus de {mois} mois :",
             "Pour chacune, pourriez-vous nous dire si elle est toujours due (et si une relance est en cours), si elle a déjà été réglée (date et mode de règlement), si elle est contestée, ou si vous la considérez comme irrécouvrable ?",
             "Client", "Factures clients"),
            (f"Factures fournisseurs non réglées depuis plus de {mois} mois", fournisseurs,
             f"Nous n'avons trouvé aucun règlement pour les factures fournisseurs suivantes, datées de plus de {mois} mois :",
             "Pourriez-vous nous confirmer qu'elles restent à régler, ou nous indiquer la date et le mode de règlement si elles ont déjà été payées ? Si l'une d'elles est contestée ou doit donner lieu à un avoir, merci de nous le préciser.",
             "Fournisseur", "Factures fournisseurs")):
        if items:
            lignes = [[_cell(x["nom"]), _cell(ref, 40), d, cf.eur(m)] for x in items for d, ref, m in x["lignes"]]
            r.append({"titre": f"{titre} ({_pl(len(lignes), 'facture')}, {cf.eur(sum((x['montant'] for x in items), ZERO))})",
                      "intro": intro, "cols": [nom, "N° de facture", "Date", "Reste dû"], "lignes": lignes, "fin": fin,
                      "nums": [m for x in items for _, _, m in x["lignes"]], "feuille": feuille})
    for titre, items, intro, fin, nom, feuille in (
            (f"Règlements de clients sans facture correspondante, de plus de {mois} mois", sf_clients,
             f"Nous n'avons pas retrouvé de facture de vente correspondant aux règlements (ou avoirs) suivants, enregistrés il y a plus de {mois} mois :",
             "Pourriez-vous nous indiquer à quelle facture ils se rapportent ou, si cette facture n'est pas dans nos écritures, nous en transmettre une copie ? S'il s'agit d'un acompte ou d'un avoir, merci de nous le préciser.",
             "Client", "Règlements clients"),
            ("Règlements de fournisseurs sans facture correspondante", sf_fournisseurs,
             "Nous n'avons pas retrouvé de facture d'achat correspondant aux règlements (ou avoirs) suivants, quelle que soit leur date :",
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


def generer(chemin, date_arrete=None, mois=3, nom_client=None, destinataire=None, signataire=None, delai=None, montant_min=10, afficher_mail=False, format_sortie="mail"):
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
    ops = operations_a_justifier(lignes, arrete)
    try:
        mini = Decimal(str(montant_min).replace(",", ".")) if str(montant_min or "").strip() else Decimal("10")
    except Exception:  # noqa: BLE001
        mini = Decimal("10")
    clients, na_c, ind_c, sf_c = tiers_en_retard(lignes, CLIENTS, "d", arrete, limite, debut, mini)
    fourn, na_f, ind_f, sf_f = tiers_en_retard(lignes, FOURNISSEURS, "c", arrete, limite, debut, mini, True)
    petits = [x for x in clients + fourn if x["montant"] < mini]
    clients = [x for x in clients if x["montant"] >= mini]
    fourn = [x for x in fourn if x["montant"] >= mini]
    rub = rubriques(ops, clients, fourn, mois, sf_c, sf_f)
    if not rub:
        return (f"Aucun point en suspens au {cf.jj(arrete)} : pas d'opération en compte d'attente (471-473), aucune facture "
                f"client ou fournisseur non réglée et aucun règlement sans facture depuis plus de {mois} mois."), None
    objet = f"Points en suspens au {cf.jj(arrete)}" + (f" – {nom_client}" if nom_client else "")
    salut = f"Bonjour {destinataire}," if destinataire else "Bonjour,"
    delai = delai or "[date limite]"
    signataire = signataire or "[Votre nom]"
    intro = intro_mail(arrete)
    texte = mail_texte(rub, objet, salut, delai, signataire, intro)
    excel = "xls" in str(format_sortie or "").lower() or "excel" in str(format_sortie or "").lower()
    nom = "points_en_suspens_" + "".join(c if c.isalnum() else "_" for c in (nom_client or "dossier"))[:30] + f"_{arrete:%Y%m%d}" + (".xlsx" if excel else ".html")
    sortie = None
    for dossier in (cf.dossier_hermes(), os.path.join(ICI, "sorties")):   # d'abord le dossier choisi dans Hermes
        if not dossier:
            continue
        try:
            os.makedirs(dossier, exist_ok=True)
            sortie = os.path.join(dossier, nom)
            if excel:
                ecrire_xlsx(sortie, rub, objet)
            else:
                with open(sortie, "w", encoding="utf-8") as f:
                    f.write(mail_html(rub, objet, salut, delai, signataire, intro))
            break
        except OSError:
            sortie = None
    if not sortie:
        raise ValueError("impossible d'ecrire le fichier du mail (dossier de travail Hermes et dossier « sorties » inaccessibles).")
    notes = [f"Base : FEC du {cf.jj(debut)} au {cf.jj(fin)}, points arrêtés au {cf.jj(arrete)} ; ancienneté = date de la pièce, "
             f"seuil {mois} mois (avant le {cf.jj(limite)}) ; les règlements non lettrés sont imputés sur les factures les plus anciennes ; "
             f"restes de facture inférieurs à {cf.eur(mini)} ignorés ; "
             "opérations à justifier = comptes 471 à 473 non lettrés."]
    if petits:
        notes.append(f"{len(petits)} tiers de moins de {cf.eur(mini)} non repris dans le mail ({cf.eur(sum((x['montant'] for x in petits), ZERO))} au total) ; les restes de facture inférieurs à ce montant sont ignorés.")
    if sf_c or sf_f:
        notes.append("À vérifier en interne avant envoi : les règlements sans facture repris ci-dessus ne sont peut-être que des lettrages manquants.")
    reste_c = sum((x[1] for x in na_c), ZERO) - sum((x["montant"] for x in sf_c), ZERO)
    reste_f = sum((x[1] for x in na_f), ZERO) - sum((x["montant"] for x in sf_f), ZERO)
    if reste_c > 0:
        notes.append(f"Règlements/avoirs de clients sans facture non repris (moins de {mois} mois ou inférieurs à {cf.eur(mini)}) : {cf.eur(reste_c)}.")
    if reste_f > 0:
        notes.append(f"Règlements/avoirs de fournisseurs sans facture non repris (inférieurs à {cf.eur(mini)}) : {cf.eur(reste_f)}.")
    if ind_c or ind_f:
        notes.append(f"Report à nouveau récent non évalué (ancienneté inconnue) : clients {cf.eur(ind_c)}, fournisseurs {cf.eur(ind_f)}.")
    if illisibles:
        notes.append(f"({illisibles} ligne(s) du FEC illisible(s), ignorée(s).)")
    notes.append((f"Fichier Excel (une feuille par rubrique) : {cf.vers_affichage(sortie)}" if excel else
                  f"Mail complet à copier dans Outlook (à ouvrir dans le navigateur) : {cf.vers_affichage(sortie)}"))
    if afficher_mail and not excel:
        notes.append("Restitue ce mail tel quel : ne modifie aucun montant ni aucun nom, ne l'envoie pas ; l'utilisateur le relit puis l'envoie.")
        return texte + "\n\n---\n" + "\n".join(notes), sortie
    resume = [("Points en suspens prêts, au format Excel" if excel else "Mail de points en suspens prêt") + f" (arrêté au {cf.jj(arrete)}) :"]
    if ops:
        resume.append(f"- Justificatifs manquants : {_pl(len(ops), 'opération')} à justifier, {cf.eur(sum((o['montant'] for o in ops), ZERO))}.")
    for nom_r, items, tiers, mot, delai_r in (("Factures clients sans règlement", clients, "client", "facture", f" depuis plus de {mois} mois"),
                                              ("Factures fournisseurs non réglées", fourn, "fournisseur", "facture", f" depuis plus de {mois} mois"),
                                              ("Règlements de clients sans facture", sf_c, "client", "règlement", f" depuis plus de {mois} mois"),
                                              ("Règlements de fournisseurs sans facture", sf_f, "fournisseur", "règlement", " (toutes dates)")):
        if items:
            n = sum(len(x["lignes"]) for x in items)
            resume.append(f"- {nom_r}{delai_r} : {_pl(n, mot)} ({_pl(len(items), tiers)}), "
                          f"{cf.eur(sum((x['montant'] for x in items), ZERO))}.")
    consigne = ("Réponds en 3 ou 4 lignes : reprends ce résumé, indique le fichier à ouvrir et, s'il y en a, la mention « à vérifier en interne » si elle figure dans les notes. "
                "NE recopie PAS le contenu et n'écris aucun tableau : il est dans le fichier. Ne l'envoie pas. "
                + ("" if excel else "Si l'utilisateur veut lire le mail dans la conversation, relance l'outil avec afficher_mail=oui."))
    return "\n".join(resume) + "\n\n---\n" + "\n".join(notes) + "\n" + consigne, sortie
