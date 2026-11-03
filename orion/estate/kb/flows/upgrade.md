# Phone upgrade flow

1. `web-storefront` builds an upgrade cart (`POST /v2/carts`), carrying the current line in `currentLine.msisdn`.
2. `order-service` asks `catalog-service` for the plan and calls `billing-adapter` for an **estimate**
   (`/subscriptions/estimate`).
3. `billing-adapter` forwards the estimate to `billing-core`. `billing-core` validates mandatory fields:
   `msisdn`, `item_name` and `order_type`.

Billing error `BILL-4004 MANDATORY_FIELD_MISSING` means a mandatory field reached billing empty.
`billing-core` is the system of record; it rejects bad input, it does not create it.
Look upstream at the service that built the request.
