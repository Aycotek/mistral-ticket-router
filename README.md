# Tri de tickets support avec Mistral

**Démo en ligne : [aycotek.github.io/mistral-ticket-router](https://aycotek.github.io/mistral-ticket-router/)**

Un opérateur fibre reçoit des centaines de messages clients par jour. Chacun doit être lu,
classé, priorisé et envoyé à la bonne équipe. Ce projet automatise ce tri avec les modèles
Mistral et, surtout, **mesure si ça vaut le coup** : qualité, urgences ratées, coût, gain net.

> J'ai mené ce type de projet en production en entreprise (modèle open source sur Azure,
> **-25 % de temps opérateur par jour**), puis recommandé sa mise en pause quand des réponses
> types apportaient l'essentiel du gain pour moins cher. Ce dépôt reprend le cas d'usage avec
> les modèles Mistral et une méthode d'évaluation complète. Aucune donnée réelle n'est utilisée.

## Ce que fait l'outil

Un message entre, une décision sort :

```text
« Pharmacie du Centre : notre terminal de télétransmission vers la sécu ne passe plus
  depuis ce matin, la box clignote. On ne peut plus facturer les ordonnances. »

  catégorie   panne
  priorité    P1 (bloquant)
  équipe      Support technique
  résumé      Pharmacie sans connexion, télétransmission et facturation bloquées.
  revue       non (confiance suffisante)
```

## Ce qui rend le problème difficile

Une règle simple par mots-clés trie correctement **90 %** des tickets clairs. Sur les 48
tickets « pièges » du banc d'essai, elle tombe à **46 %**, et elle classe **12 urgences sur 12**
comme « pas urgentes ».

Dans ces messages, l'urgence est dans le **contexte**, pas dans les mots :

- « les bracelets d'appel des résidents ne remontent plus » : un EHPAD sans système d'alerte ;
- « le boîtier de téléassistance de ma grand-mère affiche défaut de ligne » ;
- « un journaliste m'a contacté au sujet des pannes » : un risque d'image ;
- « super la fibre... 3e soir sans netflix 👏 » : de l'ironie ;
- de l'anglais, du langage SMS, plusieurs demandes dans un même message.

Une fois les erreurs comptées, la règle par mots-clés **fait perdre environ 3 800 € par mois**
au lieu d'en faire gagner (hypothèses du calculateur : 300 tickets/jour, 6 minutes perdues par
erreur). C'est le point de référence que les modèles doivent battre.

## Résultats

| Approche | Bonne catégorie | Bonne priorité | Urgences détectées | Urgences classées « pas urgent » | Coût / 1 000 tickets |
|---|---|---|---|---|---|
| Règle par mots-clés | 67 % (standard 90 %, difficile 46 %) | 44 % | 35 % | 13 sur 20 | 0 $ |
| Ministral 8B | à lancer | | | | |
| Mistral Small | à lancer | | | | |
| Mistral Large | à lancer | | | | |

Les lignes Mistral se remplissent avec `python evaluate.py` et une clé API (voir plus bas).
La page en ligne se met à jour automatiquement avec ces résultats.

## Comment c'est construit

```text
ticket ──► LLM Mistral ──► JSON ──► validation ──► règles métier ──► décision
             lit, comprend,          valeurs         équipe, seuil
             résume                  autorisées      de confiance
```

- **Le modèle comprend, le code décide du routage.** L'équipe destinataire vient d'une table dans le code. Si l'organisation change, on modifie une ligne, sans toucher au modèle.
- **Garde-fous.** Une réponse hors liste, un JSON invalide ou une confiance trop faible envoie le ticket en revue humaine.
- **Le rappel des P1 d'abord.** Rater une urgence coûte plus cher que mal classer une question de facture.
- **Rentabilité nette.** Le calcul retire le temps perdu sur chaque erreur et le coût de l'API.
- **Aucune dépendance.** Python standard et un appel REST direct : le code tourne sur un poste, un serveur sur site ou un cloud privé. La clé API reste côté serveur.

**La méthode complète est dans [METHODE.md](METHODE.md)** : critères de succès définis avant
de coder, construction et étiquetage des données, choix techniques, protocole d'évaluation,
intervalles de confiance, formule du ROI, limites et plan de passage en production.

## Lancer le projet

Il faut Python 3.10 ou plus récent, sans aucune bibliothèque à installer.

```bash
git clone https://github.com/Aycotek/mistral-ticket-router.git
cd mistral-ticket-router

python -m unittest discover tests        # tests, sans clé (API Mistral simulée)
python evaluate.py --models baseline     # règle par mots-clés, sans clé
python router.py --offline "Plus de connexion sur tout le site, urgent"
```

Avec une clé Mistral ([console.mistral.ai](https://console.mistral.ai)) :

```bash
echo MISTRAL_API_KEY=ta_cle > .env       # fichier ignoré par git
python evaluate.py                       # baseline + Ministral 8B, Small, Large
python app.py                            # page web + démo en direct sur http://localhost:8000
```

## Organisation du dépôt

| Fichier | Rôle |
|---|---|
| `router.py` | Prompt, appel à l'API, garde-fous, règles de routage, baseline par mots-clés |
| `evaluate.py` | Évaluation sur le jeu étiqueté, indicateurs, export pour la page web |
| `app.py` | Serveur local : page web et démo en direct (la clé reste côté serveur) |
| `config.json` | Modèles comparés, tarifs, seuil de confiance |
| `data/tickets.jsonl` | 90 tickets fictifs étiquetés (42 standard, 48 difficiles) |
| `docs/` | Page web publiée sur GitHub Pages |
| `results/` | Rapport détaillé par modèle |
| `tests/` | Tests avec une API Mistral simulée |
| `METHODE.md` | Méthode complète |

---

Projet personnel d'Arthur Rolland, sans lien avec Mistral AI.
[LinkedIn](https://www.linkedin.com/in/arthur-rolland1/)
