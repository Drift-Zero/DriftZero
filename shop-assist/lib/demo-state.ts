export type ScenarioId =
  | 'healthy'
  | 'stale_returns'
  | 'inventory_mismatch'
  | 'expired_promotion'
  | 'outdated_warranty'
  | 'shipping_conflict'
  | 'recovered';

export type Scenario = {
  id: ScenarioId;
  name: string;
  shortName: string;
  description: string;
  impact: string;
  metric: string;
};

export const scenarios: Scenario[] = [
  { id: 'stale_returns', name: 'Stale returns policy', shortName: 'Returns', description: 'The retriever serves retired Returns Policy v1.4.', impact: 'Electronics and clearance eligibility becomes incorrect.', metric: 'Groundedness ↓ 41 pts' },
  { id: 'inventory_mismatch', name: 'Inventory mismatch', shortName: 'Inventory', description: 'A delayed catalog snapshot reports sold-out products as available.', impact: 'Customers receive false stock assurances.', metric: 'Factual quality ↓ 29 pts' },
  { id: 'expired_promotion', name: 'Expired promotion', shortName: 'Promotion', description: 'An expired SAVE20 campaign remains in retrieval results.', impact: 'The assistant promises an invalid discount.', metric: 'Citation match ↓ 34 pts' },
  { id: 'outdated_warranty', name: 'Outdated warranty', shortName: 'Warranty', description: 'A retired warranty overview overrides the current terms.', impact: 'Coverage length and accidental protection are misstated.', metric: 'Unsupported claims +2' },
  { id: 'shipping_conflict', name: 'Conflicting shipping guides', shortName: 'Shipping', description: 'Two indexed guides disagree on delivery timing.', impact: 'The assistant selects an unsupported faster estimate.', metric: 'Semantic stability ↓ 38 pts' },
];

export const DEFAULT_SCENARIO: ScenarioId = 'healthy';
export const SCENARIO_KEY = 'shopassist.scenario.v1';

export function readScenario(): ScenarioId {
  if (typeof window === 'undefined') return DEFAULT_SCENARIO;
  const value = window.localStorage.getItem(SCENARIO_KEY);
  const allowed: ScenarioId[] = ['healthy', 'stale_returns', 'inventory_mismatch', 'expired_promotion', 'outdated_warranty', 'shipping_conflict', 'recovered'];
  return allowed.includes(value as ScenarioId) ? (value as ScenarioId) : DEFAULT_SCENARIO;
}

export function writeScenario(value: ScenarioId) {
  window.localStorage.setItem(SCENARIO_KEY, value);
  window.dispatchEvent(new CustomEvent('shopassist:scenario', { detail: value }));
}
