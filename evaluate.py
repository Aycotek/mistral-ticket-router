"""Évalue le tri sur le jeu étiqueté, compare les modèles et exporte les résultats.

    python evaluate.py                              # baseline + tous les modèles de config.json
    python evaluate.py --models baseline            # sans clé API
    python evaluate.py --models ministral-8b-latest mistral-small-latest

Sorties :
    docs/results.json          données lues par la page web (fusionnées entre deux lancements)
    results/<modele>.md        rapport lisible par modèle
"""
import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

from router import CATEGORIES, CONFIG, SEUIL_CONFIANCE, trier, utf8_console

ICI = Path(__file__).parent
SORTIE_JSON = ICI / "docs" / "results.json"


def charger(chemin):
    with open(chemin, encoding="utf-8") as f:
        tickets = [json.loads(l) for l in f if l.strip()]
    for t in tickets:
        t.setdefault("difficulte", "standard")
        assert t["categorie"] in CATEGORIES, f"catégorie inconnue : ticket {t['id']}"
    return tickets


def wilson(k, n, z=1.96):
    """Intervalle de confiance à 95 % d'une proportion (Wilson), utile avec peu d'exemples."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    marge = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(centre - marge, 4), round(centre + marge, 4))


def metriques(paires):
    """paires = [(ticket, decision)]. Renvoie un dict d'indicateurs."""
    n = len(paires)
    if n == 0:
        return {}
    ok_cat = sum(d["categorie"] == t["categorie"] for t, d in paires)
    ok_prio = sum(d["priorite"] == t["priorite"] for t, d in paires)
    vrais_p1 = [d for t, d in paires if t["priorite"] == "P1"]
    predits_p1 = [t for t, d in paires if d["priorite"] == "P1"]
    auto = [(t, d) for t, d in paires if not d["revue_humaine"]]
    ok_auto = sum(d["categorie"] == t["categorie"] for t, d in auto)
    return {
        "n": n,
        "precision_categorie": round(ok_cat / n, 4),
        "ic95_categorie": wilson(ok_cat, n),
        "precision_priorite": round(ok_prio / n, 4),
        "rappel_p1": round(sum(d["priorite"] == "P1" for d in vrais_p1) / len(vrais_p1), 4) if vrais_p1 else None,
        "precision_p1": round(sum(t["priorite"] == "P1" for t in predits_p1) / len(predits_p1), 4) if predits_p1 else None,
        "p1_rates": sum(d["priorite"] == "P3" for d in vrais_p1),
        "taux_automatisation": round(len(auto) / n, 4),
        "precision_sur_automatise": round(ok_auto / len(auto), 4) if auto else None,
    }


def evaluer(tickets, modele):
    offline = modele == "baseline"
    paires, tok_in, tok_out, latences = [], 0, 0, []
    for t in tickets:
        d, usage, lat = trier(t["texte"], model=modele, offline=offline)
        tok_in += usage.get("prompt_tokens", 0)
        tok_out += usage.get("completion_tokens", 0)
        latences.append(lat)
        paires.append((t, d))
        ok = "ok " if d["categorie"] == t["categorie"] else "ERR"
        print(f"  [{ok}] #{t['id']:>2} attendu {t['categorie']}/{t['priorite']} -> {d['categorie']}/{d['priorite']}", flush=True)
        if not offline:
            time.sleep(0.3)  # reste sous la limite de débit des petits forfaits
    n = len(tickets)
    res = {
        "id": modele,
        "nom": "Baseline mots-clés" if offline else CONFIG["modeles"].get(modele, {}).get("nom", modele),
        "global": metriques(paires),
        "standard": metriques([p for p in paires if p[0]["difficulte"] == "standard"]),
        "difficile": metriques([p for p in paires if p[0]["difficulte"] == "difficile"]),
        "confusions": [
            {"attendu": a, "predit": b, "nb": k}
            for (a, b), k in Counter((t["categorie"], d["categorie"]) for t, d in paires if d["categorie"] != t["categorie"]).most_common()
        ],
    }
    if not offline:
        prix = CONFIG["modeles"].get(modele, {"entree": 0, "sortie": 0})
        res.update({
            "tokens_entree_moy": round(tok_in / n),
            "tokens_sortie_moy": round(tok_out / n),
            "cout_par_ticket_usd": round((tok_in * prix["entree"] + tok_out * prix["sortie"]) / 1e6 / n, 7),
            "latence_moy_s": round(statistics.mean(latences), 2),
            "latence_p95_s": round(sorted(latences)[int(0.95 * (n - 1))], 2),
            "prix": prix,
        })
    return res, {t["id"]: d for t, d in paires}


def rapport_md(r):
    g = r["global"]
    lignes = [f"# {r['nom']}", "", "| Indicateur | Global | Standard | Difficile |", "|---|---|---|---|"]
    def ligne(label, cle, fmt="{:.0%}"):
        vals = [r[s].get(cle) for s in ("global", "standard", "difficile")]
        lignes.append(f"| {label} | " + " | ".join("-" if v is None else fmt.format(v) for v in vals) + " |")
    ligne("Précision catégorie", "precision_categorie")
    ligne("Précision priorité", "precision_priorite")
    ligne("Rappel des P1", "rappel_p1")
    ligne("Précision des P1", "precision_p1")
    ligne("P1 classés P3 (grave)", "p1_rates", "{}")
    ligne("Taux d'automatisation", "taux_automatisation")
    ligne("Précision sur l'automatisé", "precision_sur_automatise")
    lo, hi = g["ic95_categorie"]
    lignes += ["", f"Intervalle de confiance à 95 % sur la précision catégorie : {lo:.0%} à {hi:.0%}."]
    if "cout_par_ticket_usd" in r:
        lignes += [f"Coût moyen : {r['cout_par_ticket_usd']:.6f} $ par ticket ; latence moyenne {r['latence_moy_s']} s (p95 {r['latence_p95_s']} s)."]
    if r["confusions"]:
        lignes += ["", "| Attendu | Prédit | Nb |", "|---|---|---|"] + [f"| {c['attendu']} | {c['predit']} | {c['nb']} |" for c in r["confusions"]]
    return "\n".join(lignes) + "\n"


def main():
    utf8_console()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", nargs="+", default=["baseline", *CONFIG["modeles"]])
    p.add_argument("--data", default=ICI / "data" / "tickets.jsonl")
    a = p.parse_args()

    tickets = charger(a.data)
    sortie = json.loads(SORTIE_JSON.read_text(encoding="utf-8")) if SORTIE_JSON.exists() else {"modeles": {}, "predictions": {}}
    (ICI / "results").mkdir(exist_ok=True)

    for m in a.models:
        print(f"\n=== {m} ===", flush=True)
        try:
            res, preds = evaluer(tickets, m)
        except RuntimeError as e:
            print(f"  ignoré : {e}")
            continue
        sortie["modeles"][m] = res
        sortie["predictions"][m] = preds
        (ICI / "results" / f"{m}.md").write_text(rapport_md(res), encoding="utf-8")
        g = res["global"]
        print(f"  -> catégorie {g['precision_categorie']:.0%}, priorité {g['precision_priorite']:.0%}, rappel P1 {g['rappel_p1']:.0%}")

    sortie.update({
        "genere_le": date.today().isoformat(),
        "seuil_confiance": SEUIL_CONFIANCE,
        "tickets": [{k: t[k] for k in ("id", "texte", "categorie", "priorite", "difficulte")} for t in tickets],
    })
    SORTIE_JSON.parent.mkdir(exist_ok=True)
    SORTIE_JSON.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nRésultats écrits dans {SORTIE_JSON}")


if __name__ == "__main__":
    main()
