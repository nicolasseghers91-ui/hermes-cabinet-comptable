"""FEC fictif pour tester controle_fec (aucune donnee reelle)."""
import sys
COLS = ["JournalCode","JournalLib","EcritureNum","EcritureDate","CompteNum","CompteLib","CompAuxNum","CompAuxLib","PieceRef","PieceDate","EcritureLib","Debit","Credit","EcritureLet","DateLet","ValidDate","Montantdevise","Idevise"]
lignes = []
def ecr(j, n, ligs, piece="", valid="20260701"):
    for (date, cpt, lib, d, c, *r) in ligs:
        aux = r[0] if r else ""
        let = r[1] if len(r) > 1 else ""
        f = lambda x: f"{x:.2f}".replace(".", ",") if x else ""
        lignes.append([j, j, str(n), date, cpt, lib, aux, aux, piece or f"P{n}", date, lib, f(d) if d else "0,00", f(c) if c else "0,00", let, "", valid, "", ""])
n = 1
# ventes equilibrees
for k in range(1, 21):
    m = f"2026{(k % 6) + 1:02d}{(k % 27) + 1:02d}"
    ecr("VT", n, [(m, "411000", "Facture client", 120.0 * k, 0, f"C{k:03d}"), (m, "706000", "Prestation", 0, 100.0 * k), (m, "445710", "TVA collectee", 0, 20.0 * k)]); n += 1
# achats equilibres
for k in range(1, 16):
    m = f"2026{(k % 6) + 1:02d}{(k % 27) + 1:02d}"
    ecr("AC", n, [(m, "606000", "Achat", 50.0 * k, 0), (m, "445660", "TVA deductible", 10.0 * k, 0), (m, "401000", "Fournisseur", 0, 60.0 * k, f"F{k:03d}")]); n += 1
# cas: ecriture PayPal etalee sur juin, lignes d'equilibre le 30/06
ecr("PA", 1892, [("20260603", "411000", "Vente paypal", 872.02, 0, "C777"), ("20260608", "706000", "Vente paypal", 0, 1000.00), ("20260630", "627802", "Frais paypal", 127.98, 0)], piece="P1892")
# cas: ecriture reellement desequilibree
ecr("OD", 55, [("20260615", "616000", "Assurance", 300.0, 0), ("20260615", "512000", "Banque", 0, 250.0)])
# cas: client crediteur (avoir sans facture) et fournisseur debiteur
ecr("VT", 900, [("20260620", "411000", "Avoir client", 0, 500.0, "C900"), ("20260620", "706000", "Avoir", 500.0, 0)])
ecr("AC", 901, [("20260621", "401000", "Avoir fournisseur", 80.0, 0, "F900"), ("20260621", "606000", "Avoir", 0, 80.0)])
# doublon
ecr("AC", 950, [("20260622", "606000", "Achat doc", 200.0, 0), ("20260622", "401000", "Fournisseur", 0, 200.0, "F950")], piece="F-100")
ecr("AC", 951, [("20260622", "606000", "Achat doc", 200.0, 0), ("20260622", "401000", "Fournisseur", 0, 200.0, "F950")], piece="F-100")
# lettrage desequilibre
ecr("BQ", 960, [("20260625", "512000", "Encaissement", 100.0, 0), ("20260625", "411000", "Reglement client", 0, 100.0, "C001", "AA")])
ecr("VT", 961, [("20260626", "411000", "Facture", 90.0, 0, "C001", "AA"), ("20260626", "706000", "Prestation", 0, 90.0)])
ligne_ent = "\t".join(COLS)
out = sys.argv[1]
with open(out, "w", encoding="cp1252", newline="") as f:
    f.write(ligne_ent + "\r\n")
    for l in lignes:
        f.write("\t".join(l) + "\r\n")
print(len(lignes), "lignes ->", out)
