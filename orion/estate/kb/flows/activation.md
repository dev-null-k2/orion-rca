# Activation flow

A customer activates a new line from the storefront or a retail agent uses the agent portal.

1. `web-storefront` posts the activation to `api-gateway` (`POST /v2/activations`).
2. `order-service` builds the activation order and calls `activation-service`.
3. `activation-service` reserves a number on the host network through `carrier-gateway`.
4. `activation-service` delivers plan benefits: it writes a **service event** row in `subscriber-db`
   (`service_events`) and then redeems the service PIN in `billing-core` through `billing-adapter`.
5. `notification-service` sends the welcome SMS.

A device that stays in status `PENDING_ACTIVATION` with no phone number assigned means step 4 never finished.
Retries from the agent portal call benefit delivery again for the same device.

Logs: `activation-*` (service `activation-service`), `db-*` for database errors.
Tables: `lines`, `devices`, `service_events`.
