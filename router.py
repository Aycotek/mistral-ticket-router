"""Triage de tickets support avec l'API Mistral.

Le LLM lit le ticket et propose une catégorie, une priorité, un résumé.
Les règles métier (équipe destinataire, seuil de confiance, valeurs autorisées)
restent dans le code : elles sont explicables, auditables et modifiables sans
toucher au modèle.

Usage :
    python router.py "Plus de connexion depuis ce matin sur tout le site"
    python router.py --model ministral-8b-latest "..."
    python router.py --offline "..."      # baseline par mots-clés, sans API
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ICI = Path(__file__).parent
API_URL = "https://api.mistral.ai/v1/chat/completions"
CONFIG = json.loads((ICI / "config.json").read_text(encoding="utf-8"))
DEFAULT_MODEL = "mistral-small-latest"
SEUIL_CONFIANCE = CONFIG["seuil_confiance"]

CATEGORIES = {
    "panne": "Perte ou dégradation du service : coupure, débit, latence, wifi, box, téléassistance.",
    "raccordement": "Éligibilité, création ou travaux de raccordement d'un logement ou d'un site.",
    "intervention": "Rendez-vous technicien : planification, absence, report, travail incomplet ou mal fait.",
    "facturation": "Factures, prélèvements, remboursements, avoirs, recouvrement, remises.",
    "commande": "Nouvelle commande, changement d'offre, devis, déménagement de contrat, suivi ADV.",
    "resiliation": "Demande, conditions ou litige de résiliation.",
    "autre": "Tout le reste : RGPD, sécurité, fraude, presse, compte client, relances, remerciements.",
}
PRIORITES = {
    "P1": "Bloquant ou à risque : site professionnel entier à l'arrêt, santé ou personnes vulnérables, sécurité des biens et personnes, risque juridique, médiatique ou financier majeur, échéance sous 48 h.",
    "P2": "Gênant : service dégradé, réclamation, délai qui dérape, client mécontent, mais une solution d'attente existe.",
    "P3": "Information, demande simple ou planifiable, pas d'impact immédiat.",
}
# Règle métier : la catégorie détermine l'équipe. On ne demande pas ça au LLM.
ROUTAGE = {
    "panne": "Support technique",
    "raccordement": "Service raccordement",
    "intervention": "Pilotage interventions",
    "facturation": "Facturation",
    "commande": "ADV",
    "resiliation": "Service client",
    "autre": "Service client",
}

SYSTEM_PROMPT = f"""Tu es l'agent de tri du support d'un opérateur fibre (clients particuliers et entreprises).
Pour chaque ticket, renvoie UNIQUEMENT un objet JSON avec ces clés :
- "categorie" : une valeur parmi {list(CATEGORIES)}
- "priorite" : "P1", "P2" ou "P3"
- "resume" : une phrase de 15 mots maximum, factuelle, en français
- "references" : liste des numéros de dossier ou de commande cités, liste vide sinon
- "confiance" : nombre entre 0 et 1, ta certitude sur la catégorie

Catégories :
{chr(10).join(f'- {k} : {v}' for k, v in CATEGORIES.items())}

Priorités : juge l'impact réel pour le client, pas le ton du message.
{chr(10).join(f'- {k} : {v}' for k, v in PRIORITES.items())}

Si le ticket contient plusieurs demandes, classe selon celle que le client présente comme la plus urgente.
Le ticket peut être dans une autre langue que le français.
"""


def charger_cle():
    """Lit MISTRAL_API_KEY depuis l'environnement ou le fichier .env (jamais versionné)."""
    if os.environ.get("MISTRAL_API_KEY"):
        return os.environ["MISTRAL_API_KEY"]
    env = ICI / ".env"
    if env.exists():
        for ligne in env.read_text(encoding="utf-8").splitlines():
            if ligne.startswith("MISTRAL_API_KEY="):
                cle = ligne.split("=", 1)[1].strip().strip('"')
                if cle and cle != "colle_ta_cle_ici":
                    return cle
    return None


def appel_mistral(texte, model=DEFAULT_MODEL, api_key=None, retries=5):
    """Appelle l'API chat en mode JSON. Renvoie (dict, usage, latence_s)."""
    api_key = api_key or charger_cle()
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY absente (variable d'environnement ou fichier .env).")
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
            try:
                return json.loads(contenu), body.get("usage", {}), latence
            except json.JSONDecodeError:
                return {}, body.get("usage", {}), latence  # sortie invalide -> revue humaine
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and tentative < retries - 1:
                time.sleep(2 ** tentative)  # backoff : limite de débit ou erreur serveur
                continue
            raise RuntimeError(f"Erreur API {e.code} : {e.read().decode(errors='replace')[:300]}")


# Baseline volontairement simple, pour vérifier que le LLM apporte quelque chose.
# Mots-clés écrits en regardant les 42 premiers tickets (les "standard") :
# elle est donc avantagée sur ceux-là et découvre les 48 "difficiles".
MOTS_CLES = {
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
    """Garde-fous : valeur hors liste ou confiance faible -> revue humaine."""
    cat, prio = brut.get("categorie"), brut.get("priorite")
    try:
        conf = float(brut.get("confiance", 0))
    except (TypeError, ValueError):
        conf = 0.0
    valide = cat in CATEGORIES and prio in PRIORITES
    refs = brut.get("references")
    return {
        "categorie": cat if valide else "autre",
        "priorite": prio if valide else "P2",
        "equipe": ROUTAGE[cat] if valide else "Revue humaine",
        "resume": str(brut.get("resume", ""))[:200],
        "references": [str(r) for r in refs] if isinstance(refs, list) else [],
        "confiance": round(conf, 2),
        "revue_humaine": (not valide) or conf < SEUIL_CONFIANCE,
    }


def trier(texte, model=DEFAULT_MODEL, offline=False):
    """Renvoie (decision, usage, latence_s)."""
    if offline:
        return valider(baseline_mots_cles(texte)), {}, 0.0
    brut, usage, latence = appel_mistral(texte, model=model)
    return valider(brut), usage, latence


def utf8_console():
    for flux in (sys.stdout, sys.stderr):
        if hasattr(flux, "reconfigure"):
            flux.reconfigure(encoding="utf-8")


def main():
    utf8_console()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("texte", help="texte du ticket")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--offline", action="store_true", help="baseline mots-clés, sans appel API")
    a = p.parse_args()
    try:
        decision, usage, latence = trier(a.texte, model=a.model, offline=a.offline)
    except RuntimeError as e:
        sys.exit(str(e))
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    if usage:
        print(f"\n{usage.get('prompt_tokens')} tokens en entrée, {usage.get('completion_tokens')} en sortie, {latence:.2f} s")


if __name__ == "__main__":
    main()
