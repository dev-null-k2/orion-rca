# Evals

`orion eval` runs three suites and a gate, and writes `results/eval-report.json` and `.md`.

## 1. End-to-end RCA

Seven incidents in the synthetic estate, each with ground truth: the root-cause service, the root file(s), facts a
correct RCA must contain, and claims it must not make. Each policy runs every incident three times with a different
seed and louder decoys (noise x1, x2, x3).

| Incident | Failure shows in | Starts in | Mechanism |
|---|---|---|---|
| upgrade-missing-login | billing-core (BILL-4004) | order-service | phone number resolved only for devices; plan items pass `null` |
| activation-npe | activation-service NPE | activation-service | insert fails on retry → service returns null → dereference |
| profile-generic-error | website message | profile-service | catch-all hides a new 30-char address limit |
| duplicate-charge | payments | payment-service | new request id per retry defeats de-duplication |
| sms-timeouts | notification-service | notification-service | 2 s timeout below the carrier's 4.5 s p99 |
| promo-expired-early | catalog-service | catalog-service | Eastern wall-clock times compared as UTC |
| gateway-misroute | api-gateway | api-gateway | route points at a host that doesn't exist after a change |

Metrics: pass@1, pass^k (all trials pass), root service/file accuracy, fact recall, forbidden claims, verification
rate, confidence when right vs wrong, tool calls, time.

Baselines and ablations: `no-walk-back` (same tools, no walk order, no tracing), `error-owner`, `loudest-error`.

## 2. Retrieval

22 questions written the way engineers ask them, each with the page that answers it. Reported for BM25, dense and
hybrid: recall@1, recall@3, MRR.

## 3. Flow routing

24 short, messy ticket texts labelled with their business flow: top-1, top-3, and how often Orion asks the engineer
because the ranking isn't clear.

## Gate

The build fails if the reference policy drops below 85% pass@1 or pass^k, makes any forbidden claim, verifies less
than 85% of answers, if retrieval recall@3 or flow top-3 drop below 85%, or if it stops beating every baseline.

## Limits

The incidents were written alongside the reference policy. Treat its 100% as a regression bar; the comparison with the
ablation and baselines is the meaningful result. Held-out incidents by other authors are on the roadmap.
