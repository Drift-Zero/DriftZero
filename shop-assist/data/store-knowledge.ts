import { orders, policySources, products } from './catalog.ts';

export const currentPolicyFacts = {
  returns: {
    sourceId: policySources.returns.id,
    general: 'Most unused items can be returned within 30 days.',
    electronics: 'Electronics can be returned within 14 days.',
    clearance: 'Clearance items are final sale unless they arrive damaged or defective.',
  },
  refunds: {
    sourceId: policySources.returns.id,
    timing: 'Approved refunds return to the original payment method within 5–7 business days.',
  },
  warranty: {
    sourceId: policySources.warranty.id,
    electronics: 'Electronics include a 12-month manufacturer warranty for defects. Accidental damage is not covered.',
  },
  shipping: {
    sourceId: policySources.shipping.id,
    standard: 'Standard shipping usually takes 3–5 business days. The order confirmation contains the specific estimate.',
  },
  promotions: {
    sourceId: policySources.promotions.id,
    current: 'There are no store-wide promotion codes active today. Product-specific markdowns appear directly in the catalog.',
  },
};

export const groundingSources = [
  { id: policySources.catalog.id, label: `${policySources.catalog.title} ${policySources.catalog.version}` },
  { id: 'demo-orders-2026-09-06', label: 'Demo Orders 6 Sep snapshot' },
  { id: policySources.returns.id, label: `${policySources.returns.title} ${policySources.returns.version}` },
  { id: policySources.warranty.id, label: `${policySources.warranty.title} ${policySources.warranty.version}` },
  { id: policySources.shipping.id, label: `${policySources.shipping.title} ${policySources.shipping.version}` },
  { id: policySources.promotions.id, label: `${policySources.promotions.title} ${policySources.promotions.version}` },
] as const;

export const currentStoreKnowledge = {
  catalogSourceId: policySources.catalog.id,
  products,
  ordersSourceId: 'demo-orders-2026-09-06',
  orders,
  policies: currentPolicyFacts,
};
