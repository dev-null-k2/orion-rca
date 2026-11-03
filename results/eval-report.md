# Orion eval report

## End-to-end RCA

| Policy | pass@1 | pass^k | Root service | Root file | Fact recall | Forbidden | Verified | Median tool calls |
|---|---|---|---|---|---|---|---|---|
| reference | 100% | 100% | 100% | 100% | 89% | 0 | 100% | 17 |
| no-walk-back | 14% | 14% | 43% | 43% | 40% | 0 | 100% | 25 |
| error-owner | 0% | 0% | 57% | 57% | 31% | 0 | 86% | 6 |
| loudest-error | 0% | 0% | 0% | 0% | 0% | 3 | 0% | 5 |

## Retrieval (KB, 22 queries)

| Mode | recall@1 | recall@3 | MRR |
|---|---|---|---|
| bm25 | 82% | 96% | 0.89 |
| dense | 86% | 100% | 0.93 |
| hybrid | 82% | 96% | 0.89 |

## Flow identification (24 tickets)

top-1 83%, top-3 100%, asks the engineer on 21%

## Gate

PASS
