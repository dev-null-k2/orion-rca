"""Card capture with retries."""
import uuid

from payment.processor import ProcessorClient, ProcessorTimeout

MAX_ATTEMPTS = 3


def capture(client: ProcessorClient, order_id: str, amount_cents: int) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            request_id = str(uuid.uuid4())
            return client.capture(order_id=order_id, amount=amount_cents, request_id=request_id)
        except ProcessorTimeout:
            if attempt == MAX_ATTEMPTS:
                raise
    raise RuntimeError("unreachable")
