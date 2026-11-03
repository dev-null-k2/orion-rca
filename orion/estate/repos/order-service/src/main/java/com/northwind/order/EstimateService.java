package com.northwind.order;

import com.northwind.billing.client.BillingClient;
import com.northwind.billing.client.Deal;
import com.northwind.billing.client.EstimateRequest;

/** Builds the billing estimate for an order (activation, upgrade, refill). */
public class EstimateService {

    private final BillingClient billing;
    private final DeviceLookup devices;

    public EstimateService(BillingClient billing, DeviceLookup devices) {
        this.billing = billing;
        this.devices = devices;
    }

    public Estimate estimate(Order order) {
        EstimateRequest request = new EstimateRequest(order.getId(), order.getType());
        for (OrderItem item : order.getItems()) {
            request.addDeal(createDeal(order, item));
        }
        return billing.estimate(request);
    }

    Deal createDeal(Order order, OrderItem item) {
        Deal deal = new Deal(item.getDealName(), order.getType());
        String serial = item.getProduct().getSerialNumber();
        // Handsets resolve the line from the device registry; plans trust the cart.
        if ("DEVICE".equals(item.getCategory())) {
            serial = devices.msisdnFor(item.getProduct().getDeviceId());
        }
        deal.setMsisdn(serial);
        deal.setAmount(item.getPrice());
        return deal;
    }
}
