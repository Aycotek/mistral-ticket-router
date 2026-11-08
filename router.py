"""Triage de tickets support avec l'API Mistral.

Le LLM classe et résume ; les règles métier (table de routage, seuil de
confiance) restent dans le code, pour rester explicables et auditables.

Usage :
    python router.py "Plus de connexion depuis ce matin sur tout le site"
    python router.py --offline "..."      # baseline par mots-clés, sans API
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODEL = "mistral-small-latest"

CATEGORIES = {
    "panne": "Perte ou dégradation de service (coupure, débit, wifi, synchro).",
    "raccordement": "Éligibilité, création ou travaux de raccordement d'un logement ou site.",
    "intervention": "Rendez-vous technicien : planification, absence, report, travail incomplet.",
    "facturation": "Factures, prélèvements, remboursements, RIB.",
    "commande": "Commandes, changements d'offre, devis, suivi ADV.",
    "resiliation": "Fin de contrat, demande ou litige de résiliation.",
    "autre": "Tout le reste (RGPD, sécurité voirie, remerciements, compte client...).",
}
PRIORITES = {
    "P1": "Bloquant : entreprise/site entier coupé, client sensible, risque sécurité, juridique ou financier majeur, échéance sous 48 h.",
    "P2": "Gênant : service dégradé, réclamation, délai qui dérape, mais contournable.",
    "P3": "Information ou demande simple, pas d'urgence.",
}
# Règle métier : la catégorie détermine l'équipe. Pas besoin de demander ça au LLM.
ROUTAGE = {
    "panne": "Support technique",
    "raccordement": "Service raccordement",
    "intervention": "Pilotage interventions",
    "facturation": "Facturation",
    "commande": "ADV",
    "resiliation": "Service client",
    "autre": "Service client",
}
SEUIL_CONFIANCE = 0.6  # en dessous : revue humaine

SYSTEM_PROMPT = f"""Tu es l'agent de tri du support d'un opérateur fibre (B2B et B2C).
Pour chaque ticket, renvoie UNIQUEMENT un objet JSON avec ces clés :
- "categorie" : une valeur parmi {list(CATEGORIES)}
- "priorite" : "P1", "P2" ou "P3"
- "resume" : une phrase de 15 mots maximum, factuelle
- "references" : liste des numéros de dossier/commande cités (ex. "CMD-77120"), vide sinon
- "confiance" : nombre entre 0 et 1

Catégories :
{chr(10).join(f'- {k} : {v}' for k, v in CATEGORIES.items())}

Priorités :
{chr(10).join(f'- {k} : {v}' for k, v in PRIORITES.items())}

Exemple :
Ticket : "Le technicien n'est pas venu ce matin, je veux un nouveau créneau."
{{"categorie": "intervention", "priorite": "P2", "resume": "Technicien absent au rendez-vous, nouveau créneau demandé.", "references": [], "confiance": 0.9}}
"""


def appel_mistral(texte, model=DEFAULT_MODEL, api_key=None, retries=4):
    """Appelle l'API chat en mode JSON. Renvoie (dict, usage, latence_s)."""
    api_key = api_key or os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        sys.exit("MISTRAL_API_KEY absente. Définis la variable ou utilise --offline.")
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Ticket : {texte}"},
        ],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    for tentative in range(retries):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.load(r)
            latence = time.perf_counter() - t0
            contenu = body["choices"][0]["message"]["content"]
            return json.loads(contenu), body.get("usage", {}), latence
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and tentative < retries - 1:
                time.sleep(2 ** tentative)  # backoff sur limite de débit / erreur serveur
                continue
            raise SystemExit(f"Erreur API {e.code} : {e.read().decode(errors='replace')[:300]}")
        except json.JSONDecodeError:
            if tentative < retries - 1:
                continue
            return {}, {}, time.perf_counter() - t0


MOTS_CLES = {  # baseline volontairement naïve, pour comparer avec le LLM
    "resiliation": ["résili", "resili", "fin à son contrat", "mettre fin"],
    "facturation": ["factur", "prélev", "rembours", "rib", "€"],
    "commande": ["commande", "cmd-", "devis", "passer de l'offre"],
    "intervention": ["technicien", "intervention", "rendez-vous", "créneau", "sous-traitant"],
    "raccordement": ["raccord", "éligible", "pto", "pbo", "fourreau"],
    "panne": ["connexion", "coupe", "débit", "wifi", "hs", "synchro", "panne"],
}
MOTS_URGENCE = ["urgence", "urgent", "critique", "bloqu", "hs", "aujourd'hui", "danger", "médiateur"]


def baseline_mots_cles(texte):
    t = texte.lower()
    cat = next((c for c, mots in MOTS_CLES.items() if any(m in t for m in mots)), "autre")
    prio = "P1" if any(m in t for m in MOTS_URGENCE) else "P3"
    return {"categorie": cat, "priorite": prio, "resume": texte[:80], "references": [], "confiance": 1.0}


def valider(brut):
    """Garde-fous : valeurs hors liste ou confiance faible -> revue humaine."""
    cat = brut.get("categorie")
    prio = brut.get("priorite")
    try:
        conf = float(brut.get("confiance", 0))
    except (TypeError, ValueError):
        conf = 0.0
    valide = cat in CATEGORIES and prio in PRIORITES
    return {
        "categorie": cat if valide else "autre",
        "priorite": prio if valide else "P2",
        "equipe": ROUTAGE.get(cat, "Service client") if valide else "Revue humaine",
        "resume": str(brut.get("resume", ""))[:200],
        "references": brut.get("references") or [],
        "confiance": conf,
        "revue_humaine": (not valide) or conf < SEUIL_CONFIANCE,
    }


def trier(texte, model=DEFAULT_MODEL, offline=False):
    """Renvoie (decision, usage, latence_s)."""
    if offline:
        return valider(baseline_mots_cles(texte)), {}, 0.0
    brut, usage, latence = appel_mistral(texte, model=model)
    return valider(brut), usage, latence


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("texte", help="texte du ticket")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--offline", action="store_true", help="baseline mots-clés, sans appel API")
    a = p.parse_args()
    decision, usage, latence = trier(a.texte, model=a.model, offline=a.offline)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    if usage:
        print(f"\n{usage.get('prompt_tokens')} tokens en entrée, {usage.get('completion_tokens')} en sortie, {latence:.2f} s")


if __name__ == "__main__":
    main()
