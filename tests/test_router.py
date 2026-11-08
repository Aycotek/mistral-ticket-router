"""Tests sans clé API : un faux serveur reproduit le format de réponse de l'API Mistral
(/v1/chat/completions) pour vérifier l'appel, l'analyse, les garde-fous et les reprises.

    python -m unittest discover tests
"""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import router  # noqa: E402

SCENARIO = {"reponses": [], "requetes": []}


def reponse_mistral(contenu):
    """Corps de réponse au format documenté de l'API chat completions."""
    return 200, {
        "id": "test", "object": "chat.completion", "model": "mistral-small-latest",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": contenu}}],
        "usage": {"prompt_tokens": 812, "completion_tokens": 64, "total_tokens": 876},
    }


class FausseAPI(BaseHTTPRequestHandler):
    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SCENARIO["requetes"].append({"auth": self.headers.get("Authorization"), "corps": corps})
        code, data = SCENARIO["reponses"].pop(0)
        brut = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(brut)))
        self.end_headers()
        self.wfile.write(brut)

    def log_message(self, *a):
        pass


class TestRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FausseAPI)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        router.API_URL = f"http://127.0.0.1:{cls.srv.server_port}/v1/chat/completions"
        router.time.sleep = lambda s: None  # pas d'attente réelle pendant les reprises

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        SCENARIO["reponses"].clear()
        SCENARIO["requetes"].clear()

    def appel(self, texte="Plus de connexion sur tout le site"):
        return router.appel_mistral(texte, api_key="cle-test")

    def test_reponse_valide(self):
        SCENARIO["reponses"].append(reponse_mistral(json.dumps(
            {"categorie": "panne", "priorite": "P1", "resume": "Site coupé.", "references": ["CMD-1"], "confiance": 0.93})))
        brut, usage, _ = self.appel()
        d = router.valider(brut)
        self.assertEqual((d["categorie"], d["priorite"], d["equipe"]), ("panne", "P1", "Support technique"))
        self.assertFalse(d["revue_humaine"])
        self.assertEqual(usage["prompt_tokens"], 812)

    def test_requete_envoyee(self):
        SCENARIO["reponses"].append(reponse_mistral('{"categorie":"autre","priorite":"P3","confiance":0.9}'))
        self.appel("bonjour")
        req = SCENARIO["requetes"][0]
        self.assertEqual(req["auth"], "Bearer cle-test")
        self.assertEqual(req["corps"]["response_format"], {"type": "json_object"})
        self.assertEqual(req["corps"]["temperature"], 0)
        self.assertEqual(req["corps"]["messages"][0]["role"], "system")
        self.assertIn("bonjour", req["corps"]["messages"][1]["content"])

    def test_json_invalide_part_en_revue(self):
        SCENARIO["reponses"].append(reponse_mistral("Voici ma réponse : panne"))
        brut, _, _ = self.appel()
        self.assertTrue(router.valider(brut)["revue_humaine"])

    def test_categorie_inventee_part_en_revue(self):
        SCENARIO["reponses"].append(reponse_mistral('{"categorie":"urgence","priorite":"P1","confiance":0.99}'))
        d = router.valider(self.appel()[0])
        self.assertTrue(d["revue_humaine"])
        self.assertEqual(d["equipe"], "Revue humaine")

    def test_confiance_faible_part_en_revue(self):
        SCENARIO["reponses"].append(reponse_mistral('{"categorie":"commande","priorite":"P3","confiance":0.4}'))
        d = router.valider(self.appel()[0])
        self.assertEqual(d["categorie"], "commande")
        self.assertTrue(d["revue_humaine"])

    def test_reprise_apres_limite_de_debit(self):
        SCENARIO["reponses"] += [(429, {"message": "rate limited"}), (503, {}), reponse_mistral('{"categorie":"facturation","priorite":"P2","confiance":0.8}')]
        self.assertEqual(self.appel()[0]["categorie"], "facturation")
        self.assertEqual(len(SCENARIO["requetes"]), 3)

    def test_erreur_definitive(self):
        SCENARIO["reponses"].append((401, {"message": "Unauthorized"}))
        with self.assertRaises(RuntimeError):
            self.appel()

    def test_sans_cle(self):
        cle = router.charger_cle
        router.charger_cle = lambda: None
        try:
            with self.assertRaises(RuntimeError):
                router.appel_mistral("x")
        finally:
            router.charger_cle = cle

    def test_jeu_de_donnees(self):
        lignes = (Path(router.ICI) / "data" / "tickets.jsonl").read_text(encoding="utf-8").splitlines()
        tickets = [json.loads(l) for l in lignes if l.strip()]
        self.assertEqual(len({t["id"] for t in tickets}), len(tickets))
        for t in tickets:
            self.assertIn(t["categorie"], router.CATEGORIES)
            self.assertIn(t["priorite"], router.PRIORITES)


if __name__ == "__main__":
    unittest.main()
