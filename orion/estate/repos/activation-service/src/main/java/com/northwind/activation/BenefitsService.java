package com.northwind.activation;

/** Delivers plan benefits after a line is provisioned. */
public class BenefitsService {

    private final ServiceEventService transactions;
    private final PinRedeemer pins;

    public BenefitsService(ServiceEventService transactions, PinRedeemer pins) {
        this.transactions = transactions;
        this.pins = pins;
    }

    public void deliver(ActivationContext ctx) {
        ServiceEvent tx = new ServiceEvent(ctx.getDeviceId(), "ACTIVATION", ctx.getTxDate());
        tx = transactions.create(tx);
        ctx.setServiceEventId(tx.getId());
        pins.redeem(ctx.getPin(), ctx.getMsisdn());
        ctx.markActive();
    }
}
