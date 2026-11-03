# Subscriber database

Tables: `accounts`, `lines`, `devices`, `orders`, `service_events`, `payments`, `promotions`.
`service_events` has a unique index `ux_service_event (device_id, action, tx_date)`.
Orion reads it with SELECT only, inside read-only connections.
