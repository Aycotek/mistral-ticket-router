"""Évalue le tri sur le jeu étiqueté et chiffre coût et ROI.

    python evaluate.py --offline                       # baseline mots-clés
    python evaluate.py --model mistral-small-latest
    python evaluate.py --model ministral-8b-latest

Le rapport Markdown est écrit dans results/.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from router import CATEGORIES, DEFAULT_MODEL, trier

ICI = Path(__file__).parent


def charger(chemin):
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def evaluer(tickets, model, offline):
    lignes, tok_in, tok_out, latences = [], 0, 0, []
    for t in tickets:
        d, usage, lat = trier(t["texte"], model=model, offline=offline)
        tok_in += usage.get("prompt_tokens", 0)
        tok_out += usage.get("completion_tokens", 0)
        latences.append(lat)
        lignes.append((t, d))
        ok = "ok " if d["categorie"] == t["categorie"] else "ERR"
        print(f"[{ok}] #{t['id']:>2} attendu {t['categorie']}/{t['priorite']} -> {d['categorie']}/{d['priorite']}", flush=True)
    return lignes, tok_in, tok_out, latences


def rapport(lignes, tok_in, tok_out, latences, a):
    n = len(lignes)
    acc_cat = sum(d["categorie"] == t["categorie"] for t, d in lignes) / n
    acc_prio = sum(d["priorite"] == t["priorite"] for t, d in lignes) / n
    p1 = [(t, d) for t, d in lignes if t["priorite"] == "P1"]
    rappel_p1 = sum(d["priorite"] == "P1" for _, d in p1) / len(p1)
    revue = sum(d["revue_humaine"] for _, d in lignes) / n
    erreurs = [(t, d) for t, d in lignes if d["categorie"] != t["categorie"]]
    confusion = Counter((t["categorie"], d["categorie"]) for t, d in erreurs)

    nom = "baseline mots-clés" if a.offline else a.model
    out = [f"# Résultats : {nom}", "", f"Jeu de test : {n} tickets synthétiques (opérateur fibre, FR).", ""]
    out += ["| Indicateur | Valeur |", "|---|---|",
            f"| Précision catégorie | {acc_cat:.0%} |",
            f"| Précision priorité | {acc_prio:.0%} |",
            f"| Rappel des P1 (urgences détectées) | {rappel_p1:.0%} |",
            f"| Envoyés en revue humaine | {revue:.0%} |"]

    if not a.offline:
        cout_ticket = (tok_in * a.prix_entree + tok_out * a.prix_sortie) / 1e6 / n
        lat_moy = sum(latences) / n
        cout_mois = cout_ticket * a.tickets_jour * 22
        gain_mois = a.tickets_jour * 22 * a.minutes_gagnees / 60 * a.cout_horaire * acc_cat
        out += [f"| Latence moyenne | {lat_moy:.2f} s |",
                f"| Tokens moyens / ticket | {tok_in / n:.0f} entrée, {tok_out / n:.0f} sortie |",
                f"| Coût API / ticket | {cout_ticket:.5f} $ |",
                "", "## Estimation de ROI (hypothèses à adapter au client)", "",
                f"- {a.tickets_jour} tickets/jour, 22 jours/mois, {a.minutes_gagnees} min gagnées par ticket bien trié, {a.cout_horaire} €/h chargé",
                f"- Coût API : **{cout_mois:,.0f} $/mois**",
                f"- Temps opérateur économisé : **{gain_mois:,.0f} €/mois** (pondéré par la précision)",
                f"- Tarifs utilisés : {a.prix_entree} $ / {a.prix_sortie} $ par million de tokens (à vérifier sur mistral.ai/pricing)",
                "- Non inclus : intégration à l'outil de ticketing, supervision, conduite du changement."]

    if confusion:
        out += ["", "## Confusions principales", "", "| Attendu | Prédit | Nb |", "|---|---|---|"]
        out += [f"| {att} | {pred} | {k} |" for (att, pred), k in confusion.most_common()]
        out += ["", "## Tickets mal classés", ""]
        out += [f"- #{t['id']} ({t['categorie']} -> {d['categorie']}) : {t['texte'][:110]}" for t, d in erreurs]
    return "\n".join(out) + "\n"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--offline", action="store_true")
    p.add_argument("--data", default=ICI / "data" / "tickets.jsonl")
    p.add_argument("--prix-entree", type=float, default=0.1, help="$ par million de tokens en entrée")
    p.add_argument("--prix-sortie", type=float, default=0.3, help="$ par million de tokens en sortie")
    p.add_argument("--tickets-jour", type=int, default=300)
    p.add_argument("--minutes-gagnees", type=float, default=1.5)
    p.add_argument("--cout-horaire", type=float, default=35.0)
    a = p.parse_args()

    tickets = charger(a.data)
    assert all(t["categorie"] in CATEGORIES for t in tickets), "catégorie inconnue dans le jeu de test"
    md = rapport(*evaluer(tickets, a.model, a.offline), a)
    dossier = ICI / "results"
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"rapport_{'baseline' if a.offline else a.model}.md"
    fichier.write_text(md, encoding="utf-8")
    print("\n" + md + f"\nRapport écrit dans {fichier}")


if __name__ == "__main__":
    main()
