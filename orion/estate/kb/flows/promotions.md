# Promotions flow

`catalog-service` owns promotions. Each promotion has `starts_at` and `ends_at`.
Promotions are defined in US Eastern time by the marketing team; `catalog-service` stores UTC.
`order-service` asks `catalog-service` whether a promo code is valid when the cart is priced.

Error: `CAT-3007 PROMO_EXPIRED`.
