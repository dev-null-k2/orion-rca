# Refill flow

Customers refill airtime with a card or a PIN.

1. `api-gateway` → `order-service` builds the refill order.
2. Card refills call `payment-service` to authorise the card, then `billing-adapter` to add balance.
3. PIN refills call `billing-adapter` directly to redeem the PIN.
4. `notification-service` sends the receipt SMS.

Errors: `PAY-1201 AUTH_DECLINED`, `BILL-2100 BALANCE_UPDATE_FAILED`.
