"""FEC fictifs (N et N-1) pour tester tableau_bord, un par type de dossier. Aucune donnee reelle."""
import os
import random
import sys

COLS = ["JournalCode","JournalLib","EcritureNum","EcritureDate","CompteNum","CompteLib","CompAuxNum","CompAuxLib","PieceRef","PieceDate","EcritureLib","Debit","Credit","EcritureLet","DateLet","ValidDate","Montantdevise","Idevise"]
LIBS = {"411000": "Clients", "401000": "Fournisseurs", "512000": "Banque", "706000": "Prestations de services", "707000": "Ventes de marchandises", "708000": "Activites annexes",
        "607000": "Achats de marchandises", "604000": "Sous-traitance", "603700": "Variation de stock marchandises", "310000": "Stock de marchandises", "606000": "Energie, fournitures",
        "613000": "Locations", "616000": "Assurances", "622000": "Honoraires", "627000": "Services bancaires", "641000": "Salaires", "645000": "Charges sociales", "635100": "Taxes",
        "661000": "Interets d'emprunt", "681100": "Dotations amortissements", "445710": "TVA collectee", "445660": "TVA deductible", "101000": "Capital", "120000": "Resultat",
        "646000": "Cotisations exploitant", "625100": "Deplacements", "706100": "Loyers appartement A", "706200": "Loyers appartement B", "164000": "Emprunt bancaire", "213000": "Immeuble",
        "615000": "Entretien reparations", "614000": "Charges de copropriete", "635120": "Taxe fonciere", "695000": "Impot sur les societes", "756000": "Cotisations", "754000": "Dons manuels",
        "741100": "Subvention Etat", "744100": "Subvention Region", "441000": "Subventions a recevoir", "689000": "Engagements a realiser", "789000": "Report ressources non utilisees",
        "194000": "Fonds dedies sur subventions", "731100": "Dotation globalisee", "706800": "Hebergement residents", "601000": "Achats alimentation", "633000": "Taxe sur salaires", "631000": "Taxe sur salaires 631",
        "108000": "Compte de l'exploitant", "700000": "Honoraires"}


class Gen:
    def __init__(self, annee, seed):
        self.l, self.n, self.a = [], 1, annee
        self.r = random.Random(seed)

    def ecr(self, j, date, lignes, piece=None):
        for cpt, d, c, *rest in lignes:
            f = lambda x: f"{x:.2f}".replace(".", ",") if x else "0,00"
            aux = rest[0] if rest else ""
            self.l.append([j, j, str(self.n), date, cpt, LIBS.get(cpt, cpt), aux, aux, piece or f"P{self.n}", date, "Ecriture", f(d), f(c), "", "", "", "", ""])
        self.n += 1

    def dt(self, m, jour=15):
        return f"{self.a}{m:02d}{jour:02d}"

    def ecrire(self, chemin):
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8", newline="") as f:
            f.write("\t".join(COLS) + "\n")
            for x in self.l:
                f.write("\t".join(x) + "\n")


def vente(g, m, ht, cpt="706000", tva=0.20, jour=10):
    t = ht * tva
    g.ecr("VT", g.dt(m, jour), [("411000", ht + t, 0, "C001"), (cpt, 0, ht), ("445710", 0, t)])
    g.ecr("BQ", g.dt(m, min(28, jour + 12)), [("512000", ht + t, 0), ("411000", 0, ht + t, "C001")])


def achat(g, m, ht, cpt, tva=0.20, jour=12):
    t = ht * tva
    g.ecr("AC", g.dt(m, jour), [(cpt, ht, 0), ("445660", t, 0), ("401000", 0, ht + t, "F001")])
    g.ecr("BQ", g.dt(m, min(28, jour + 10)), [("401000", ht + t, 0, "F001"), ("512000", 0, ht + t)])


def charge_banque(g, m, mont, cpt, jour=20):
    g.ecr("BQ", g.dt(m, jour), [(cpt, mont, 0), ("512000", 0, mont)])


def bic(annee, mois, k, seed, avec_603=True):
    g = Gen(annee, seed)
    g.ecr("AN", g.dt(1, 1), [("512000", 18000, 0), ("411000", 14000, 0), ("310000", 6000, 0), ("213000", 30000, 0),
                              ("101000", 0, 10000), ("401000", 0, 9000), ("164000", 0, 20000), ("120000", 0, 29000)])
    for m in range(1, mois + 1):
        f = 1 + 0.03 * m + g.r.uniform(-0.05, 0.05)
        vente(g, m, 12000 * k * f, "707000")
        vente(g, m, 7000 * k * f, "706000")
        achat(g, m, 6500 * k * f, "607000")
        achat(g, m, 1800 * k * f, "604000")
        achat(g, m, 900 * k, "606000")
        charge_banque(g, m, 1500, "613000")
        charge_banque(g, m, 400, "616000")
        charge_banque(g, m, 600 * k, "622000")
        g.ecr("OD", g.dt(m, 28), [("641000", 5200 * k, 0), ("645000", 2100 * k, 0), ("512000", 0, 7300 * k)])
        charge_banque(g, m, 180, "661000")
        charge_banque(g, m, 90, "627000")
    if annee == 2026:
        g.ecr("BQ", g.dt(5, 20), [("627000", 3200, 0), ("512000", 0, 3200)])   # virement interne passe en charge (anomalie voulue)
    if avec_603:
        g.ecr("OD", g.dt(mois, 28), [("310000", 4500 * k, 0), ("603700", 0, 4500 * k)])
    g.ecr("OD", g.dt(mois, 28), [("681100", 1500, 0), ("213000", 0, 1500)])
    return g


def bnc(annee, mois, k, seed):
    g = Gen(annee, seed)
    g.ecr("AN", g.dt(1, 1), [("512000", 9000, 0), ("101000", 0, 9000)])
    for m in range(1, mois + 1):
        f = 1 + 0.02 * m + g.r.uniform(-0.05, 0.05)
        for _ in range(3):
            g.ecr("BQ", g.dt(m, g.r.randint(2, 27)), [("512000", 4200 * k * f, 0), ("700000", 0, 4200 * k * f)])
        charge_banque(g, m, 2400 * k, "622000")
        charge_banque(g, m, 1100, "613000")
        charge_banque(g, m, 260, "616000")
        charge_banque(g, m, 520 * k, "646000")
        charge_banque(g, m, 210, "625100")
        charge_banque(g, m, 60, "627000")
        g.ecr("OD", g.dt(m, 28), [("641000", 1600, 0), ("645000", 640, 0), ("512000", 0, 2240)])
    return g


def sci(annee, mois, k, seed, is_=False):
    g = Gen(annee, seed)
    g.ecr("AN", g.dt(1, 1), [("213000", 260000, 0), ("512000", 7000, 0), ("101000", 0, 60000), ("164000", 0, 205000), ("120000", 0, 2000)])
    for m in range(1, mois + 1):
        if not (annee == 2026 and m in (4, 5)):
            g.ecr("BQ", g.dt(m, 5), [("512000", 750 * k, 0), ("706100", 0, 750 * k)])
        g.ecr("BQ", g.dt(m, 6), [("512000", 620 * k, 0), ("706200", 0, 620 * k)])
        g.ecr("BQ", g.dt(m, 8), [("661000", 480, 0), ("164000", 640, 0), ("512000", 0, 1120)])
        charge_banque(g, m, 85, "616000")
        charge_banque(g, m, 70, "614000")
        if m in (3, 9):
            charge_banque(g, m, 1300 * k, "615000")
    g.ecr("BQ", g.dt(min(mois, 10), 20), [("635120", 2100, 0), ("512000", 0, 2100)])
    g.ecr("BQ", g.dt(mois, 27), [("622000", 840, 0), ("512000", 0, 840)])
    if is_:
        g.ecr("OD", g.dt(mois, 28), [("681100", 6500, 0), ("213000", 0, 6500)])
        g.ecr("OD", g.dt(mois, 28), [("695000", 900, 0), ("512000", 0, 900)])
    return g


def asso(annee, mois, k, seed):
    g = Gen(annee, seed)
    g.ecr("AN", g.dt(1, 1), [("512000", 62000, 0), ("441000", 15000, 0), ("101000", 0, 30000), ("194000", 0, 14000), ("401000", 0, 8000), ("120000", 0, 25000)])
    for m in range(1, mois + 1):
        g.ecr("BQ", g.dt(m, 10), [("512000", 4000 * k, 0), ("741100", 0, 4000 * k)])
        if m % 3 == 1:
            g.ecr("BQ", g.dt(m, 12), [("512000", 2500 * k, 0), ("744100", 0, 2500 * k)])
        g.ecr("BQ", g.dt(m, 14), [("512000", 700 * k, 0), ("756000", 0, 700 * k)])
        g.ecr("BQ", g.dt(m, 16), [("512000", 450 * k, 0), ("754000", 0, 450 * k)])
        g.ecr("BQ", g.dt(m, 18), [("512000", 900 * k, 0), ("706000", 0, 900 * k)])
        g.ecr("OD", g.dt(m, 28), [("641000", 5600 * k, 0), ("645000", 2300 * k, 0), ("512000", 0, 7900 * k)])
        charge_banque(g, m, 950, "613000")
        charge_banque(g, m, 700 * k, "606000")
        charge_banque(g, m, 120, "616000")
        charge_banque(g, m, 260 * k, "625100")
    g.ecr("OD", g.dt(mois, 28), [("689000", 3000, 0), ("194000", 0, 3000)])
    g.ecr("OD", g.dt(mois, 28), [("194000", 2200, 0), ("789000", 0, 2200)])
    return g


def esms(annee, mois, k, seed):
    g = Gen(annee, seed)
    g.ecr("AN", g.dt(1, 1), [("512000", 85000, 0), ("411000", 48000, 0), ("213000", 600000, 0), ("101000", 0, 250000), ("401000", 0, 31000), ("164000", 0, 400000), ("120000", 0, 52000)])
    for m in range(1, mois + 1):
        g.ecr("BQ", g.dt(m, 8), [("512000", 52000 * k, 0), ("731100", 0, 52000 * k)])
        g.ecr("VT", g.dt(m, 5), [("411000", 14000 * k, 0), ("706800", 0, 14000 * k)])
        g.ecr("OD", g.dt(m, 28), [("641000", 41000 * k, 0), ("645000", 15500 * k, 0), ("633000", 1600 * k, 0), ("512000", 0, 58100 * k)])
        charge_banque(g, m, 5600 * k, "601000")
        charge_banque(g, m, 3200, "606000")
        charge_banque(g, m, 2900, "613000")
        charge_banque(g, m, 1500, "616000")
        charge_banque(g, m, 1300, "661000")
    g.ecr("OD", g.dt(mois, 28), [("681100", 14000, 0), ("213000", 0, 14000)])
    return g


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fec_test"
    bic(2026, 8, 1.0, 1).ecrire(f"{d}/bic_N.txt")
    bic(2025, 12, 0.95, 2).ecrire(f"{d}/bic_N1.txt")
    bnc(2026, 9, 1.0, 3).ecrire(f"{d}/bnc_N.txt")
    bnc(2025, 12, 0.9, 4).ecrire(f"{d}/bnc_N1.txt")
    sci(2026, 12, 1.0, 5).ecrire(f"{d}/sci_ir_N.txt")
    sci(2025, 12, 0.97, 6).ecrire(f"{d}/sci_ir_N1.txt")
    sci(2026, 12, 1.0, 7, True).ecrire(f"{d}/sci_is_N.txt")
    asso(2026, 10, 1.0, 8).ecrire(f"{d}/asso_N.txt")
    asso(2025, 12, 0.95, 9).ecrire(f"{d}/asso_N1.txt")
    esms(2026, 6, 1.0, 10).ecrire(f"{d}/esms_N.txt")
    esms(2025, 12, 0.98, 11).ecrire(f"{d}/esms_N1.txt")
    print("ok")
