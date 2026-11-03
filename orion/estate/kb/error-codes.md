# Error codes

| Code | Service | Meaning |
|---|---|---|
| BILL-4004 MANDATORY_FIELD_MISSING | billing-core | A mandatory field (msisdn, item_name, order_type) was empty |
| BILL-2100 BALANCE_UPDATE_FAILED | billing-core | Balance could not be written |
| DB-0001 UNIQUE_CONSTRAINT | subscriber-db | A row with the same key already exists (e.g. `ux_service_event`) |
| PRF-2001 ACCOUNT_NOT_UPDATED | profile-service | Generic profile update failure |
| PAY-1201 AUTH_DECLINED | payment-service | Card issuer declined |
| CAT-3007 PROMO_EXPIRED | catalog-service | Promo code outside its window |
| NTF-5004 SMS_SEND_TIMEOUT | notification-service | SMS send timed out |
| GW-0502 UPSTREAM_UNAVAILABLE | api-gateway | Upstream refused or not found |
| CAR-0429 RATE_LIMITED | carrier-gateway | Host network throttled us (noisy, usually harmless) |
