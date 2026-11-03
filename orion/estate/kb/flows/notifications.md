# Notifications flow

`notification-service` sends SMS through `carrier-gateway` (one-time codes, receipts, welcome texts).
The carrier SMS API has a p99 latency of about 4.5 seconds at peak.

Error: `NTF-5004 SMS_SEND_TIMEOUT` (the client gave up before the carrier answered).
A message that timed out on our side may still be delivered late, or not at all.
