# Résultats : baseline mots-clés

Jeu de test : 42 tickets synthétiques (opérateur fibre, FR).

| Indicateur | Valeur |
|---|---|
| Précision catégorie | 90% |
| Précision priorité | 57% |
| Rappel des P1 (urgences détectées) | 88% |
| Envoyés en revue humaine | 0% |

## Confusions principales

| Attendu | Prédit | Nb |
|---|---|---|
| autre | intervention | 2 |
| raccordement | intervention | 1 |
| intervention | facturation | 1 |

## Tickets mal classés

- #8 (raccordement -> intervention) : Le technicien a dit que le PTO n'est pas posé dans l'appartement, il faut un raccordement complet. Quel est le
- #17 (intervention -> facturation) : Compte rendu d'intervention incomplet pour le dossier INT-58213, impossible de clôturer la facturation du pres
- #37 (autre -> intervention) : Bonjour, avez-vous des offres d'emploi pour technicien fibre dans la région ?
- #38 (autre -> intervention) : Je voulais remercier le technicien Julien pour son professionnalisme lors de l'installation.
