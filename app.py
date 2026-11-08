"""Serveur local : tableau de bord + démo en direct.

    python app.py            puis ouvrir http://localhost:8000

La clé API reste côté serveur (fichier .env) : le navigateur ne la voit jamais.
Sur GitHub Pages, la même page fonctionne sans ce serveur, en lecture seule.
"""
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from router import CONFIG, DEFAULT_MODEL, charger_cle, trier, utf8_console

DOCS = Path(__file__).parent / "docs"
PORT = 8000


class Handler(SimpleHTTPRequestHandler):
    def _json(self, code, data):
        corps = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        if self.path == "/api/status":
            return self._json(200, {"live": bool(charger_cle()), "modeles": CONFIG["modeles"], "defaut": DEFAULT_MODEL})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/trier":
            return self._json(404, {"erreur": "inconnu"})
        try:
            longueur = min(int(self.headers.get("Content-Length", 0)), 20_000)
            demande = json.loads(self.rfile.read(longueur))
            texte = str(demande.get("texte", "")).strip()[:4000]
            modele = demande.get("modele", DEFAULT_MODEL)
            if not texte:
                return self._json(400, {"erreur": "texte vide"})
            if modele not in CONFIG["modeles"]:
                return self._json(400, {"erreur": "modèle non autorisé"})
            decision, usage, latence = trier(texte, model=modele)
            return self._json(200, {"decision": decision, "usage": usage, "latence_s": round(latence, 2)})
        except Exception as e:  # la démo ne doit jamais planter le serveur
            return self._json(500, {"erreur": str(e)[:300]})


def main():
    utf8_console()
    print(f"Démo : http://localhost:{PORT}  (clé API {'détectée' if charger_cle() else 'absente : mode lecture seule'})")
    ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(DOCS))).serve_forever()


if __name__ == "__main__":
    main()
