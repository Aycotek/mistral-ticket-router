# Méthode

Ce document explique comment le projet a été construit, comment il est évalué et ce que les
résultats permettent (ou non) de conclure. Il suit les étapes d'un vrai déploiement chez un
client : cadrer le problème, définir la mesure du succès, construire le plus simple qui
marche, mesurer, puis décider.

---

## 1. Le problème métier

Chez un opérateur fibre, chaque message client (mail, formulaire, portail partenaire) doit être
lu par un opérateur qui décide :

- **de quoi il s'agit** : panne, raccordement, intervention, facturation, commande, résiliation, autre ;
- **à quel point c'est urgent** : P1 bloquant, P2 gênant, P3 simple ;
- **à quelle équipe l'envoyer**.

Ce tri initial est répétitif, mais les erreurs coûtent cher. Un ticket mal routé repart dans
la file d'une autre équipe et perd des heures. Une urgence ratée (un EHPAD, une pharmacie,
un site professionnel à l'arrêt) a un impact humain, commercial et parfois médiatique.

**Origine du projet.** J'ai mené ce type de projet en entreprise (alternance, DOSI d'un
opérateur fibre) : un modèle open source hébergé sur Azure, testé en production, qui
réduisait de 25 % le temps opérateur par jour. Il a ensuite été mis en pause : des réponses
types bien construites apportaient l'essentiel du gain pour un coût plus faible. Ce dépôt
reprend le cas d'usage avec les modèles Mistral et une évaluation plus rigoureuse. **Aucune
donnée de cette entreprise n'est utilisée ici.**

## 2. Ce qu'on considère comme un succès (défini avant de coder)

| Question | Indicateur | Pourquoi |
|---|---|---|
| Le ticket va-t-il à la bonne équipe ? | Précision de la catégorie | C'est elle qui détermine le routage. |
| L'urgence est-elle bien jugée ? | Précision de la priorité | Elle détermine l'ordre de traitement. |
| **Rate-t-on des urgences ?** | **Rappel des P1** et nombre de P1 classés P3 | L'erreur la plus grave. On préfère une fausse alerte à une urgence oubliée. |
| Les alertes sont-elles crédibles ? | Précision des P1 | Trop de fausses urgences, et les équipes ne les croient plus. |
| Combien de travail est vraiment retiré ? | Taux d'automatisation et précision sur cette part | Un modèle qui envoie tout en revue humaine ne sert à rien. |
| Est-ce rentable ? | Coût par ticket, délai, gain net mensuel | La décision finale est économique. |

## 3. Les données

### 3.1 Construction

90 tickets **fictifs**, écrits à la main pour reproduire les situations réelles d'un support
fibre B2B et B2C, puis étiquetés (catégorie et priorité attendues) dans `data/tickets.jsonl`.

| | Nombre |
|---|---|
| Tickets « standard » (formulation claire, un seul sujet) | 42 |
| Tickets « difficiles » | 48 |
| Dont urgences P1 | 20 |
| Répartition des catégories | 10 à 18 tickets chacune |

### 3.2 Pourquoi deux niveaux de difficulté

Les tickets **difficiles** couvrent les cas où une approche simple échoue :

- **urgence implicite** : « les bracelets d'appel des résidents ne remontent plus » (EHPAD), « terminal de télétransmission » (pharmacie), téléassistance d'une personne âgée ;
- **ironie** : « super la fibre... 3e soir sans netflix 👏 » ;
- **langage SMS, majuscules, colère** ;
- **anglais** ;
- **plusieurs demandes dans un message** : panne + question de facture, avec une priorité indiquée par le client ;
- **ton trompeur** : un message calme qui annonce une coupure dans 5 jours, un client furieux pour un sujet non urgent ;
- **risques non techniques** : journaliste, avocat, mise en demeure, fraude par hameçonnage ;
- **messages vides de sens** (« test », « rappelez-moi ») qui doivent finir dans « autre ».

### 3.3 Règles d'étiquetage

- **Catégorie** = le sujet que l'équipe destinataire doit traiter en premier. Pour un message à plusieurs demandes, c'est celle que le client présente comme prioritaire.
- **P1** si au moins un critère est rempli : site professionnel entier à l'arrêt, santé ou personne vulnérable, sécurité des biens ou des personnes, risque juridique, médiatique ou financier majeur, échéance sous 48 h.
- **P2** si le service est dégradé ou si le client est mécontent, mais qu'une solution d'attente existe.
- **P3** pour une information ou une demande planifiable.

## 4. Architecture

```
ticket ──► LLM Mistral ──► JSON brut ──► validation ──► règles métier ──► décision
             (lit, comprend,               (valeurs       (équipe, seuil
              résume)                       autorisées)     de confiance)
```

**Choix 1. Le LLM classe, le code route.** Le modèle ne choisit pas l'équipe. Il donne
une catégorie, et une table de correspondance dans le code choisit l'équipe. Si
l'organisation change (fusion de deux équipes, nouveau prestataire), on modifie une ligne de
code, pas le prompt, et il n'y a pas besoin de réévaluer le modèle.

**Choix 2. Une sortie structurée et vérifiée.** L'API est appelée en mode JSON, avec une
température à 0 pour des réponses reproductibles. Chaque réponse est contrôlée : une catégorie ou
une priorité hors liste, ou un JSON invalide, envoie le ticket en **revue humaine**.

**Choix 3. Un seuil de confiance.** Le modèle donne une confiance entre 0 et 1. Sous le
seuil (0,7, dans `config.json`), le ticket va en revue humaine. Le seuil se règle selon le
coût d'une erreur chez le client.

**Choix 4. Aucune dépendance.** Python standard et un appel REST direct. Le code
fonctionne sur un poste de travail, un serveur sur site ou un cloud privé, sans rien installer.
La clé API reste côté serveur (`.env`) et n'est jamais envoyée au navigateur.

## 5. Le prompt

Le prompt système (`router.py`, variable `SYSTEM_PROMPT`) contient :

1. le rôle (agent de tri d'un opérateur fibre) ;
2. le format de sortie exact, clé par clé ;
3. la **définition** de chaque catégorie et de chaque priorité, tirée des règles d'étiquetage ;
4. trois consignes générales : juger l'impact réel et non le ton, prendre la demande la plus urgente quand il y en a plusieurs, accepter une autre langue.

Il ne contient **aucun exemple tiré du jeu de test**. Il n'a pas été ajusté ticket par ticket
pour améliorer le score : c'est le même prompt pour tous les modèles.

## 6. Protocole d'évaluation

- Chaque modèle trie les 90 tickets, avec le même prompt et une température de 0.
- On compare quatre approches :
  - **Baseline mots-clés** : une règle écrite à la main en regardant les 42 tickets standard. C'est volontairement la solution « sans IA ». Elle est avantagée sur les tickets standard et découvre les difficiles.
  - **Ministral 8B** : petit modèle, le moins cher.
  - **Mistral Small** : modèle intermédiaire.
  - **Mistral Large** : modèle le plus capable.
- Chaque indicateur est calculé sur l'ensemble, puis séparément sur les tickets standard et difficiles.
- La précision de la catégorie est donnée avec un **intervalle de confiance à 95 %** (méthode de Wilson). Avec 90 tickets, un écart de 3 points entre deux modèles n'est pas significatif, et l'intervalle le montre.
- Le coût est calculé à partir des tokens réellement consommés, renvoyés par l'API, multipliés par le tarif de `config.json`.
- Le délai est mesuré pour chaque appel. On donne la moyenne et le 95ᵉ centile.

Pour reproduire :

```bash
python evaluate.py                     # baseline + les 3 modèles
python evaluate.py --models baseline   # sans clé API
```

## 7. Calcul du ROI

Le calculateur de la page web applique la formule suivante, par mois :

```
tickets          = tickets_par_jour × jours_ouvrés
automatisés      = tickets × taux_automatisation
bien triés       = automatisés × précision_sur_automatisé
mal triés        = automatisés − bien triés

gain             = bien triés × minutes_gagnées / 60 × coût_horaire
perte            = mal triés  × minutes_perdues / 60 × coût_horaire
coût API         = tickets × coût_par_ticket
gain net         = gain − perte − coût API
```

Deux points comptent dans cette formule :

- **Les erreurs coûtent.** Un ticket mal routé fait perdre plus de temps qu'un tri manuel : il faut le relire, le renvoyer, et le client attend. Par défaut, 6 minutes perdues par erreur contre 1,5 minute gagnée par ticket bien trié. Avec ces hypothèses, une solution précise à 67 % **perd de l'argent**. C'est le cas de la baseline.
- **Ce qui n'est pas compté :** l'intégration à l'outil de ticketing, la supervision, la formation des équipes. Chez un vrai client, ces coûts se chiffrent à part, dans le business case.

## 8. Résultats

Voir le [tableau du README](README.md#résultats) et la [page interactive](https://aycotek.github.io/mistral-ticket-router/).
Les rapports détaillés par modèle sont dans [`results/`](results/).

## 9. Limites (à connaître avant de tirer des conclusions)

- **Données fictives.** Les tickets ont été écrits pour être réalistes, mais les vrais messages sont plus longs, plus bruités (signatures, historiques de mails), et leur répartition entre catégories est différente.
- **Un seul annotateur.** La même personne a écrit les tickets, les étiquettes et le prompt. La priorité est en partie subjective : entre P2 et P3, deux opérateurs ne seraient pas toujours d'accord. En conditions réelles, on ferait étiqueter un échantillon par deux personnes pour mesurer leur accord, qui est le plafond de performance atteignable.
- **Petit échantillon.** 90 tickets suffisent pour voir de grosses différences (règle contre LLM), pas pour départager finement deux modèles proches. D'où les intervalles de confiance.
- **Tarifs.** Les prix de `config.json` sont à confirmer dans la console Mistral au moment de l'usage.
- **Confiance déclarée par le modèle.** C'est une estimation donnée par le modèle lui-même, pas une probabilité calibrée. Elle sert de signal d'alerte, à valider sur données réelles.

## 10. Passer en production chez un client

1. **Cadrage (1 semaine).** Valider les catégories avec les chefs d'équipe, chiffrer le volume et le coût d'une erreur, choisir le seuil de confiance.
2. **Jeu d'évaluation réel (2 à 3 jours).** Environ 500 tickets historiques étiquetés par deux personnes du support. On mesure leur accord.
3. **Mode observation (2 semaines).** Le modèle propose, l'opérateur décide. On mesure l'accord entre les deux, sans risque pour les clients.
4. **Mise en service progressive.** On automatise d'abord les catégories qui dépassent le seuil de qualité fixé ensemble ; le reste reste manuel.
5. **Suivi mensuel.** Précision, P1 ratés, volume en revue humaine, coût. On ajuste le prompt ou on envisage un petit modèle affiné si le volume le justifie.
6. **Savoir s'arrêter.** Si une solution plus simple (réponses types, formulaire mieux conçu) capte l'essentiel de la valeur, c'est elle qu'il faut recommander.
