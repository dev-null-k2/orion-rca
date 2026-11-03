package com.northwind.billing;

/** REST adapter: forwards estimates to billing-core unchanged. */
public class SubscriptionController {

    private final BillingCore core;
    private final Logger log = Logger.get("billing-adapter");

    public SubscriptionController(BillingCore core) {
        this.core = core;
    }

    public EstimateResponse estimate(EstimateRequest request) {
        log.info("estimate request order=" + request.getOrderId() + " deals=" + request.describeDeals());
        EstimateResponse response = core.estimate(request);
        if (!response.isOk()) {
            log.error("estimate rejected order=" + request.getOrderId() + " code=" + response.getCode());
        }
        return response;
    }
}
