# My Account (profile) flow

1. `web-storefront` sends `PUT /v2/accounts/{id}/profile` to `api-gateway`.
2. `profile-service` validates the change and writes `subscriber-db`.
3. Any failure is mapped to a customer message by `profile-service` error codes:
   `PRF-2001` → "Your changes could not be saved".

`PRF-2001` is a generic code: the real reason is only visible in `profile-service` logs if it is logged.
