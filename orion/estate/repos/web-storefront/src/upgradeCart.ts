// Builds the upgrade cart sent to POST /v2/carts.
export function buildUpgradeCart(session: Session, plan: Plan, device: Device) {
  return {
    type: "UPGRADE",
    currentLine: { msisdn: session.activeLine?.msisdn },
    items: [
      { category: "DEVICE", product: { deviceId: device.id } },
      { category: "PLAN", dealName: plan.dealName, product: { serialNumber: session.activeLine?.serial } },
    ],
  };
}
