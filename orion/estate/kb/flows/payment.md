# Payment flow

`payment-service` authorises and captures card payments through the card processor.
It retries calls that time out. Every capture **must** carry an idempotency key so that a retry
cannot capture twice; the processor de-duplicates on that key for 24 hours.

Symptoms of a missing idempotency key: customers charged twice for one order, two `capture ok`
lines with the same `order_id` and different `processor_ref`.

Logs: `payment-*`. Table: `payments`.
