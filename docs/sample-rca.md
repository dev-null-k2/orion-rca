# NWM-2041: Phone upgrade estimates failing: BILL-4004 MANDATORY_FIELD_MISSING

**Confidence** ●●●●○ 4/5 · **Verification** verified · **Critic** agree · **Flow** upgrade · **Failure shows in** billing-core

## Summary

Phone upgrade estimates failing: BILL-4004 MANDATORY_FIELD_MISSING. Root cause: order-service (partial fallback) in EstimateService.java; the failure shows in billing-core.

## Root cause

In `order-service/src/main/java/com/northwind/order/EstimateService.java` line 33 (`deal.setMsisdn(serial);`): 'serial' is only resolved in one branch (line 31); other branches pass the request value through unchecked. This is where the request in `c-5120` goes wrong: estimate built order=ORD-55120 deals=[DEVICE msisdn=5550142233, PLAN msisdn=null] [E11, E10, E8]

*observed* · `order-service/src/main/java/com/northwind/order/EstimateService.java:33`

## How it fails

1. web-storefront INFO: POST /v2/carts type=UPGRADE account=ACC-7731 order=ORD-55120 [E8]
2. order-service INFO: estimate built order=ORD-55120 deals=[DEVICE msisdn=5550142233, PLAN msisdn=null] [E8]
3. billing-adapter INFO: estimate request order=ORD-55120 deals=[DEVICE msisdn=5550142233, PLAN msisdn=null] [E8]
4. billing-core ERROR: BILL-4004 MANDATORY_FIELD_MISSING field=msisdn order=ORD-55120 item=PLAN [E8]
5. billing-adapter ERROR: BILL-4004 estimate rejected order=ORD-55120 code=BILL-4004 [E8]
6. web-storefront WARN: checkout failed order=ORD-55120 showing spinner timeout [E8]
7. The failure shows in billing-core because error BILL-4004 is raised by billing-core. [E1, E5]
8. Database before the search: account: id=ACC-7731, brand=NWM, status=ACTIVE, address_line1=12 Elm St; order: id=ORD-55120, account_id=ACC-7731, type=UPGRADE, status=FAILED, created=2026-08-21T16:32:19Z [E2, E3]
9. A comparable request in order-service worked: estimate built order=ORD-55098 deals=[DEVICE msisdn=5550190011, PLAN msisdn=5550190011] [E13]
10. 'BILL-4004': 10 in the incident window vs 9 the day before (steady). [E15]
11. Knowledge base: flows/upgrade.md#Phone upgrade flow [E16]

## Ruled out

- billing-core is where the failure shows, not where it starts: in request c-5120 the problem is already present upstream in order-service. [E8]
- carrier-gateway is the loudest service (720 warnings) but logs nothing for the failing request. [E17, E8]

## Fix

`order-service/src/main/java/com/northwind/order/EstimateService.java`: Resolve the value for every item category (look it up from the device or line registry) and reject the order before calling downstream if it is still empty. [E11]

## Open questions

- No recent change in order-service; why did this start now?

## Evidence

| Id | System | Tool | What it showed |
|---|---|---|---|
| E1 | ticket | `ticket_read` | ticket NWM-2041: Phone upgrade estimates failing: BILL-4004 MANDATORY_FIELD_MISSING |
| E2 | sql | `sql_query` | 1 row(s): SELECT * FROM accounts WHERE id = 'ACC-7731' |
| E3 | sql | `sql_query` | 1 row(s): SELECT * FROM orders WHERE id = 'ORD-55120' |
| E4 | sql | `sql_query` | 0 row(s): SELECT * FROM payments WHERE order_id = 'ORD-55120' |
| E5 | kb | `kb_search` | 2 KB passage(s) for 'error codes table service meaning' |
| E6 | logs | `logs_search` | 10 log line(s) for '*' in billing-core [2026-08-21T15:00:00.000Z .. 2026-08-21T18:00:00.000Z] |
| E7 | logs | `logs_search` | 0 log line(s) for '*' in billing-core [2026-08-21T15:00:00.000Z .. 2026-08-21T18:00:00.000Z] |
| E8 | logs | `logs_trace` | 6 line(s) for request c-5120 across 4 service(s) |
| E9 | code | `code_files` | 1 file(s) in order-service |
| E10 | code | `code_lint` | 1 finding(s) in order-service/src/main/java/com/northwind/order/EstimateService.java |
| E11 | code | `code_read` | order-service/src/main/java/com/northwind/order/EstimateService.java lines 25-37 of 37 |
| E12 | code | `code_search` | 1 match(es) for 'setMsisdn' in order-service |
| E13 | logs | `logs_search` | 2 log line(s) for 'estimate built' in order-service [2026-08-21T15:00:00.000Z .. 2026-08-21T18:00:00.000Z] |
| E14 | changes | `changes_recent` | 0 merged change(s) in order-service in the 45 days before the ticket |
| E15 | logs | `logs_compare_windows` | 'BILL-4004': 10 in the incident window vs 9 the day before (steady) |
| E16 | kb | `kb_search` | 4 KB passage(s) for 'order-service partial fallback BILL-4004' |
| E17 | logs | `logs_count_by_service` | counts by service for 'WARN' |

*17 tool calls · 17 signed evidence records · 0.17s*
