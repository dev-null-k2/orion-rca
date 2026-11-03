"""SMS sender. Talks to the carrier SMS API through carrier-gateway."""
from notify.http import post

SMS_TIMEOUT_SECONDS = 2.0


def send_sms(msisdn: str, text: str) -> bool:
    response = post("/carrier/sms", json={"to": msisdn, "text": text}, timeout=SMS_TIMEOUT_SECONDS)
    return response.ok
