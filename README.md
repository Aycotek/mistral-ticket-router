# Mistral Ticket Router

Support-ticket triage for a fibre telecom operator, built on the Mistral API.
A rebuild of an AI ticketing project I ran in production (open-source model on Azure,
**-25% operator time per day**), redone with Mistral models and a proper evaluation.

> 🇫🇷 Les tickets et le prompt sont en français : le cas d'usage est celui d'un opérateur fibre français.

## What it does

For each incoming ticket the model returns a **category**, a **priority** (P1–P3),
a **one-line summary** and any **order / case references** it finds (e.g. `CMD-77120`).

```
python router.py "Lien fibre de notre agence totalement HS, la téléphonie IP est coupée aussi."
{
  "categorie": "panne",
  "priorite": "P1",
  "equipe": "Support technique",
  "resume": "...",
  "references": [],
  "confiance": 0.95,
  "revue_humaine": false
}
```

## Design choices

| Choice | Why |
|---|---|
| The LLM classifies; **routing stays a business rule** in code | Teams change more often than categories. A rule is auditable and costs nothing. |
| JSON mode, `temperature=0`, output **validated** against allowed values | Downstream systems need predictable fields. Anything off-list goes to a human. |
| **Confidence threshold → human review** | The goal is to remove routine work, not to remove humans from edge cases. |
| **P1 recall** tracked separately | Missing an outage on a business site costs far more than a misfiled invoice question. |
| Keyword baseline included | An AI project has to beat the simple option, or it shouldn't ship. |
| Standard library only, plain REST call | Zero dependencies: easy to run on-prem or in a customer's VPC. |

## Run it

```bash
python evaluate.py --offline                          # keyword baseline, no API key needed
export MISTRAL_API_KEY=...                            # PowerShell: $env:MISTRAL_API_KEY="..."
python evaluate.py --model mistral-small-latest
python evaluate.py --model ministral-8b-latest
```

`evaluate.py` writes a Markdown report to `results/`. It covers accuracy, P1 recall,
human-review rate, latency, cost per ticket, and an ROI estimate whose assumptions
(`--tickets-jour`, `--minutes-gagnees`, `--cout-horaire`, `--prix-entree`, `--prix-sortie`)
you set for each customer.

## Results

| | Category | Priority | P1 recall |
|---|---|---|---|
| Keyword baseline | 90% * | 57% | 88% |
| `mistral-small-latest` | *run pending* | | |
| `ministral-8b-latest` | *run pending* | | |

\* The keywords were written with the test set in view, so this number is optimistic.
Priority is where rules break down: urgency depends on context (a hospital, a business
site, a legal threat), not on keywords.

The 42 tickets are **synthetic**. No real customer data is used.

## What I'd do next with a customer

1. Replace the synthetic set with ~500 real tickets labelled by the support team (2 days of their time).
2. Shadow mode for 2 weeks: the model suggests, operators decide, and we measure agreement.
3. Go live on the categories above 95% precision. The rest stays manual.
4. Watch drift monthly. If volumes or accuracy plateau, consider fine-tuning a small model.
5. Know when to stop. In my original project, standard reply templates turned out to capture
   most of the value at lower cost, so we paused the model and documented how to restart it.
