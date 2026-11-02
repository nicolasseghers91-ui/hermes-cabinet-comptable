#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Serveur MCP « Analyse comptable » (stdio) : controles exacts sur des fichiers comptables locaux.

Distinct du serveur « Doctrine fiscale » : ici le calcul est fait en Python sur le fichier (qui ne quitte pas le PC),
le modele n'a qu'a commenter le resultat. Outils : controler_fec, lister_fichiers_comptables.
Lancement : python analyse_comptable_mcp.py
"""
import json
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import controle_fec  # noqa: E402
import points_suspens  # noqa: E402
import tableau_bord  # noqa: E402

VERSION = "0.4"

OUTILS = [
    {
        "name": "controler_fec",
        "description": (
            "Controle de coherence d'un FEC (fichier des ecritures comptables, .txt) enregistre sur le PC. Calcul exact, "
            "sans toi : total debit/credit, ecritures desequilibrees, ecritures « a cheval » sur une date d'arret (cause "
            "habituelle d'un ecart a une date donnee), soldes de sens inhabituel, ecritures en double, lettrages, comptes d'attente, plus des controles propres au type de dossier (bic, bnc, sci_ir = revenus fonciers, sci_is, association, esms : "
            "compte courant d'associe, IS, amortissements, TVA, emprunt, fonds dedies...). "
            "A UTILISER quand on demande pourquoi un FEC ou une balance est desequilibre(e), s'il y a un ecart a une date, "
            "ou si des ecritures sont incoherentes. SEUL « chemin » est utile : donne le nom du fichier tel que l'utilisateur "
            "l'ecrit (ex. FEC_Pseudonymise.txt), l'outil le retrouve seul ; ne demande pas ou il se trouve. Si l'utilisateur "
            "parle d'un ecart a une date, passe-la dans date_arrete (JJ/MM/AAAA). Tous les autres parametres sont facultatifs : "
            "ne les demande JAMAIS a l'utilisateur et laisse-les vides, SAUF type_dossier a renseigner seulement si l'utilisateur a dit la nature du dossier (ex. « c'est une SARL » -> bic) ; sinon vide, ne le demande pas. « ecriture » sert uniquement, APRES un premier controle, "
            "a afficher les lignes d'une ecriture que l'outil a deja citee (format JOURNAL:NUMERO exactement comme renvoye, ex. PA:P1892). "
            "Si un fichier est joint a la conversation, NE LE LIS PAS (trop volumineux) et n'ecris pas de code. "
            "Ne refais JAMAIS les additions toi-meme : cite les chiffres renvoyes."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chemin": {"type": "string", "description": "OBLIGATOIRE, seul parametre utile pour un controle complet. Nom du fichier FEC (ex. FEC_Pseudonymise.txt) ou chemin complet"},
                "date_arrete": {"type": ["string", "null"], "description": "Date d'arret JJ/MM/AAAA a renseigner si l'utilisateur signale un ecart ou un desequilibre a une date (ex. 10/06/2026)"},
                "type_dossier": {"type": ["string", "null"], "description": "Facultatif : bic (SAS, SARL, EURL, EI), bnc, sci_ir (revenus fonciers), sci_is, association ou esms, seulement si l'utilisateur l'a dit ; sinon laisser vide sans le demander"},
                "ecriture": {"type": ["string", "null"], "description": "Facultatif, laisser vide au premier appel : JOURNAL:NUMERO d'une ecriture deja citee par l'outil, pour en voir les lignes (ex. PA:P1892)"},
                "exercice_debut": {"type": ["string", "null"], "description": "Facultatif, laisser vide : debut d'exercice JJ/MM/AAAA (signale les lignes hors exercice)"},
                "exercice_fin": {"type": ["string", "null"], "description": "Facultatif, laisser vide : fin d'exercice JJ/MM/AAAA"},
            },
        },
    },
    {
        "name": "tableau_de_bord",
        "description": (
            "Tableau de bord de gestion calcule par programme a partir d'un FEC enregistre sur le PC : fichier HTML complet "
            "(onglets, graphiques, comparaison N-1) + synthese chiffree. Types de dossier : bic (SAS, SARL, EURL, EI), bnc (liberaux), "
            "sci_ir, sci_is, association, esms. A UTILISER pour « fais-moi un tableau de bord », un point de gestion, un suivi mensuel, "
            "une analyse de la rentabilite ou de la tresorerie d'un dossier. Si le type de dossier n'est pas donne par l'utilisateur, "
            "demande-le AVANT d'appeler l'outil (ne devine pas ; SCI : IR ou IS ?). Si un fichier est joint a la conversation, NE LE LIS PAS "
            "et n'ecris pas de code : donne son nom dans chemin. Pour comparer avec l'annee precedente, donne aussi le FEC N-1 dans chemin_n1 "
            "(sinon aucune comparaison, n'invente jamais de N-1). Ne refais aucun calcul : cite les chiffres renvoyes et indique a l'utilisateur "
            "le chemin du fichier HTML a ouvrir. Ne reclasse aucune ecriture sans l'accord de l'utilisateur."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chemin": {"type": "string", "description": "OBLIGATOIRE. Nom du FEC de l'exercice N (ex. FEC_2026.txt) ou chemin complet"},
                "type_dossier": {"type": ["string", "null"], "description": "bic, bnc, sci_ir, sci_is, association ou esms (a demander a l'utilisateur s'il ne l'a pas dit)"},
                "chemin_n1": {"type": ["string", "null"], "description": "Optionnel : nom du FEC de l'exercice precedent, pour les comparaisons N / N-1"},
                "date_arrete": {"type": ["string", "null"], "description": "Optionnel : date d'arret JJ/MM/AAAA (ecritures posterieures ignorees)"},
                "nom_client": {"type": ["string", "null"], "description": "Optionnel : nom du dossier affiche dans le titre (pseudonyme possible)"},
                "valeur_bien": {"type": ["number", "string", "null"], "description": "Optionnel, SCI : valeur du bien en euros (calcul du rendement)"},
                "surface_m2": {"type": ["number", "string", "null"], "description": "Optionnel, SCI : surface totale en m2 (cout de detention au m2)"},
                "journees_realisees": {"type": ["number", "string", "null"], "description": "Optionnel, esms : journees realisees sur la periode"},
                "journees_theoriques": {"type": ["number", "string", "null"], "description": "Optionnel, esms : journees theoriques (capacite x jours) sur la periode"},
            },
        },
    },
    {
        "name": "points_en_suspens",
        "description": (
            "Prepare le MAIL de demande d'information au client a partir de son FEC (calcul exact par programme, sans toi) : "
            "operations bancaires a justifier (comptes d'attente 471-473 = pieces manquantes), clients dont les factures sont impayees "
            "depuis plus de 3 mois, fournisseurs dont les factures ne sont pas reglees depuis plus de 3 mois, reglements de clients et de "
            "fournisseurs sans facture correspondante. Ecrit le mail complet dans un fichier HTML a copier dans Outlook et renvoie un resume. A UTILISER pour « points en suspens », "
            "« pieces manquantes », « relance », « clients / fournisseurs non payes », « mail de demande d'information ». "
            "SEUL « chemin » est utile (nom du fichier tel que l'utilisateur l'ecrit) ; les autres parametres sont facultatifs et ne se "
            "demandent pas. Si un fichier est joint a la conversation, NE LE LIS PAS et n'ecris pas de code. "
            "Le mail complet est ecrit dans un fichier HTML : reponds en quelques lignes avec le resume et le chemin du fichier, sans recopier le mail ; ne l'envoie pas."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chemin": {"type": "string", "description": "OBLIGATOIRE. Nom du FEC (ex. FEC_2026.txt) ou chemin complet"},
                "date_arrete": {"type": ["string", "null"], "description": "Facultatif : date d'arret JJ/MM/AAAA (par defaut : derniere ecriture du FEC)"},
                "mois": {"type": ["number", "string", "null"], "description": "Facultatif : anciennete en mois au-dela de laquelle une facture impayee est reprise (defaut 3)"},
                "nom_client": {"type": ["string", "null"], "description": "Facultatif : nom du dossier, repris dans l'objet du mail"},
                "destinataire": {"type": ["string", "null"], "description": "Facultatif : nom de la personne a qui s'adresse le mail (Bonjour ...)"},
                "signataire": {"type": ["string", "null"], "description": "Facultatif : nom de l'expediteur (signature)"},
                "delai": {"type": ["string", "null"], "description": "Facultatif : date limite de reponse JJ/MM/AAAA"},
                "montant_min": {"type": ["number", "string", "null"], "description": "Facultatif : montant en euros en dessous duquel un tiers n'est pas repris (defaut 10)"},
                "format": {"type": ["string", "null"], "description": "Facultatif : « excel » seulement si l'utilisateur veut un fichier Excel au lieu du mail"},
                "afficher_mail": {"type": ["string", "boolean", "null"], "description": "Facultatif, laisser vide : mettre « oui » seulement si l'utilisateur demande a lire le mail dans la conversation (sinon le mail est dans le fichier HTML)"},
            },
        },
    },
    {
        "name": "lister_fichiers_comptables",
        "description": ("Liste les fichiers .txt / .csv recents (FEC, balances) trouves sur le PC dans les dossiers habituels, "
                        "pieces jointes de la conversation comprises. A utiliser si le nom du fichier est incertain."),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

ALIAS_CHEMIN = ("fichier", "path", "file", "fec", "nom", "nom_fichier", "chemin_fichier", "filename", "fec_n", "chemin_n")
ALIAS_TDB = {
    "type_dossier": ("type", "typologie", "dossier_type", "type_de_dossier", "forme", "regime"),
    "chemin_n1": ("fec_n1", "n1", "n_1", "chemin_n_1", "fichier_n1", "fec_n_1", "fec_precedent", "chemin_precedent"),
    "date_arrete": ("date", "arrete", "date_arret", "date_d_arrete"),
    "nom_client": ("client", "nom_du_client", "dossier", "societe", "raison_sociale"),
    "valeur_bien": ("valeur", "valeur_du_bien", "prix"),
    "surface_m2": ("surface", "m2"),
    "journees_realisees": ("journees", "journees_reelles", "realisees"),
    "journees_theoriques": ("theoriques", "journees_prevues", "capacite"),
}


def _nombre(v):
    """« 280 000 », « 280000,5 », 280000 -> float ; vide -> None."""
    if v in (None, "", "null", "None"):
        return None
    try:
        return float(str(v).replace(" ", "").replace("\u202f", "").replace("\xa0", "").replace("€", "").replace(",", "."))
    except ValueError:
        raise ValueError(f"valeur numerique illisible : {v}")


def appeler_outil(nom, a):
    a = dict(a or {})
    if isinstance(a.get("params"), dict) and "chemin" not in a:
        a = dict(a["params"])
    if nom == "lister_fichiers_comptables":
        return controle_fec.lister_fichiers()
    if nom == "points_en_suspens":
        if not str(a.get("chemin") or "").strip():
            for alias in ALIAS_CHEMIN:
                if str(a.get(alias) or "").strip():
                    a["chemin"] = a[alias]
                    break
        if not str(a.get("chemin") or "").strip():
            raise ValueError("argument obligatoire manquant : chemin. Relance points_en_suspens avec le nom du FEC "
                             "(ex. chemin=\"FEC_2026.txt\"), ou appelle d'abord lister_fichiers_comptables.")
        for cible, alias in {**ALIAS_TDB, "mois": ("anciennete", "duree", "delai_mois", "seuil_mois"),
                             "destinataire": ("contact", "interlocuteur", "a_l_attention_de"),
                             "signataire": ("signature", "expediteur", "auteur"),
                             "delai": ("date_limite", "echeance", "reponse_avant"),
                             "montant_min": ("seuil", "minimum", "montant_minimum")}.items():
            if cible in ("mois", "destinataire", "signataire", "delai", "montant_min", "date_arrete", "nom_client") and a.get(cible) in (None, ""):
                for al in alias:
                    if a.get(al) not in (None, ""):
                        a[cible] = a[al]
                        break
        vide = lambda v: None if v in (None, "", "null", "None") else v
        texte, _ = points_suspens.generer(
            controle_fec.resoudre_chemin(a["chemin"]), vide(a.get("date_arrete")), vide(a.get("mois")) or 3,
            vide(a.get("nom_client")), vide(a.get("destinataire")), vide(a.get("signataire")), vide(a.get("delai")),
            vide(a.get("montant_min")) or 10, str(a.get("afficher_mail") or "").strip().lower() in ("oui", "true", "1", "vrai", "yes"),
            vide(a.get("format")) or "mail")
        return texte
    if nom == "tableau_de_bord":
        if not str(a.get("chemin") or "").strip():
            for alias in ALIAS_CHEMIN:
                if str(a.get(alias) or "").strip():
                    a["chemin"] = a[alias]
                    break
        if not str(a.get("chemin") or "").strip():
            raise ValueError("argument obligatoire manquant : chemin. Relance tableau_de_bord avec le nom du FEC "
                             "(ex. chemin=\"FEC_2026.txt\"), ou appelle d'abord lister_fichiers_comptables.")
        for cible, alias in ALIAS_TDB.items():
            if a.get(cible) in (None, ""):
                for al in alias:
                    if a.get(al) not in (None, ""):
                        a[cible] = a[al]
                        break
        vide = lambda v: None if v in (None, "", "null", "None") else v
        n1 = vide(a.get("chemin_n1"))
        texte, _ = tableau_bord.generer(
            controle_fec.resoudre_chemin(a["chemin"]), vide(a.get("type_dossier")),
            chemin_n1=controle_fec.resoudre_chemin(n1) if n1 else None,
            date_arrete=vide(a.get("date_arrete")), nom_client=vide(a.get("nom_client")),
            valeur_bien=_nombre(a.get("valeur_bien")), surface_m2=_nombre(a.get("surface_m2")),
            journees_realisees=_nombre(a.get("journees_realisees")), journees_theoriques=_nombre(a.get("journees_theoriques")))
        return texte
    if nom == "controler_fec":
        if not str(a.get("chemin") or "").strip():
            for alias in ALIAS_CHEMIN:
                if str(a.get(alias) or "").strip():
                    a["chemin"] = a[alias]
                    break
        if not str(a.get("chemin") or "").strip():
            raise ValueError("argument obligatoire manquant : chemin. Relance controler_fec avec le nom du fichier "
                             "(ex. chemin=\"FEC.txt\"), ou appelle d'abord lister_fichiers_comptables.")
        def propre(v):
            v = str(v or "").strip()
            return None if v.lower() in ("", "null", "none", "toutes", "tout", "toute", "all", "*", "aucune", "n/a", "-") else v
        ch = controle_fec.resoudre_chemin(a["chemin"])
        ecr = propre(a.get("ecriture"))
        typ = None
        for cle in ("type_dossier", "type", "typologie", "dossier_type", "forme", "regime"):
            if propre(a.get(cle)):
                typ = tableau_bord.normaliser_type(a[cle])
                break
        res = controle_fec.analyser(ch, propre(a.get("date_arrete")), ecr, propre(a.get("exercice_debut")), propre(a.get("exercice_fin")), typ)
        if ecr and res.startswith("Ecriture «") and "introuvable" in res.split("\n", 1)[0]:
            res = (f"(L'ecriture « {ecr} » n'existe pas : controle complet du fichier effectue a la place. Ne demande pas de numero d'ecriture a l'utilisateur.)\n"
                   + controle_fec.analyser(ch, propre(a.get("date_arrete")), None, propre(a.get("exercice_debut")), propre(a.get("exercice_fin")), typ))
        return res
    raise ValueError(f"Outil inconnu : {nom}")


def ecrire(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def traiter(msg):
    methode, id_, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if methode is None or id_ is None:
        return
    if methode == "initialize":
        ecrire({"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": params.get("protocolVersion") or "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "analyse-comptable", "version": VERSION}}})
    elif methode == "ping":
        ecrire({"jsonrpc": "2.0", "id": id_, "result": {}})
    elif methode == "tools/list":
        ecrire({"jsonrpc": "2.0", "id": id_, "result": {"tools": OUTILS}})
    elif methode == "tools/call":
        try:
            texte = appeler_outil(params.get("name"), params.get("arguments") or {})
            ecrire({"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": texte}], "isError": False}})
        except Exception as e:  # noqa: BLE001
            ecrire({"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": f"Erreur : {e}"}], "isError": True}})
    elif methode in ("resources/list", "prompts/list"):
        ecrire({"jsonrpc": "2.0", "id": id_, "result": {("resources" if methode == "resources/list" else "prompts"): []}})
    else:
        ecrire({"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"Methode inconnue : {methode}"}})


def main():
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
            traiter(json.loads(ligne))
        except Exception as e:  # noqa: BLE001
            print("erreur interne :", e, file=sys.stderr)


if __name__ == "__main__":
    main()
