export type HallucinationTestId =
  | 'live_data_change'
  | 'made_up_detail'
  | 'wrong_number'
  | 'wrong_record'
  | 'policy_mismatch';

type LegacyScenarioId =
  | 'product_information_changed'
  | 'fake_product_detail'
  | 'wrong_order_status'
  | 'policy_hallucination'
  | 'contradiction_earlier_answer'
  | 'missing_information'
  | 'outdated_information'
  | 'conflicting_sources'
  | 'unsupported_recommendation'
  | 'wrong_numerical_answer'
  | 'entity_mix_up'
  | 'source_removed'
  | 'stale_returns'
  | 'inventory_mismatch'
  | 'expired_promotion'
  | 'outdated_warranty'
  | 'shipping_conflict';

export type ScenarioId =
  | 'healthy'
  | HallucinationTestId
  | LegacyScenarioId
  | 'recovered';

export type ScenarioSelection = ScenarioId | readonly ScenarioId[];

export type ScenarioMode =
  | 'inventory_mismatch'
  | 'fake_product_detail'
  | 'wrong_order_status'
  | 'stale_returns'
  | 'contradiction_earlier_answer'
  | 'missing_information'
  | 'expired_promotion'
  | 'outdated_warranty'
  | 'shipping_conflict'
  | 'unsupported_recommendation'
  | 'wrong_numerical_answer'
  | 'entity_mix_up'
  | 'healthy'
  | 'recovered';

export type Scenario = {
  id: HallucinationTestId;
  name: string;
  shortName: string;
  category:
    | 'Data Change'
    | 'Unsupported Claim'
    | 'Number'
    | 'Record'
    | 'Policy';
  situation: string;
  whatHappens: string;
  expected: string;
  failure: string;
  impact: { level: 'Low' | 'Medium' | 'High'; detail: string };
  steps: string[];
  detector: string;
  passResult?: string;
  failResult: string;
};

export const scenarios: Scenario[] = [
  {
    id: 'live_data_change',
    name: 'Live Data Change',
    shortName: 'Live Data Change',
    category: 'Data Change',
    situation: "Stock changes after the AI's first answer.",
    whatHappens: 'Inventory changes while the chatbot is being used.',
    expected:
      'Use the newest trusted stock value, even when it differs from the earlier answer.',
    failure: 'The AI repeats the old stock value after the source changes.',
    impact: {
      level: 'Medium',
      detail: 'A customer may act on availability that is no longer current.',
    },
    steps: [
      'Set AeroBuds stock to 50.',
      'Ask the chatbot how many are in stock.',
      'Change the trusted stock value to 48.',
      'Ask the same question again.',
      'Check the answer against the source valid at that moment.',
    ],
    detector:
      'Whether the answer uses the source value that was current when it was generated.',
    passResult: 'SUPPORTED — source changed, so the new answer is valid.',
    failResult: 'STALE — the AI is using outdated information.',
  },
  {
    id: 'made_up_detail',
    name: 'Made-Up Detail',
    shortName: 'Made-Up Detail',
    category: 'Unsupported Claim',
    situation:
      'AI claims a product has a feature that is not in the trusted source.',
    whatHappens:
      'The user asks whether AeroBuds are waterproof, but the catalog never says they are.',
    expected: 'Say the detail is not available or not confirmed.',
    failure: 'The AI confidently invents waterproofing.',
    impact: {
      level: 'Medium',
      detail:
        'A customer may buy a product based on a feature it does not have.',
    },
    steps: [
      'Load the trusted AeroBuds details.',
      'Ask whether AeroBuds are waterproof.',
      'Compare the answer with every available product field.',
      'Flag any feature that has no supporting source.',
    ],
    detector: 'A factual product claim with no supporting source.',
    failResult: 'UNSUPPORTED CLAIM — no trusted source supports this detail.',
  },
  {
    id: 'wrong_number',
    name: 'Wrong Number',
    shortName: 'Wrong Number',
    category: 'Number',
    situation: 'AI gives a number that does not match the trusted source.',
    whatHappens:
      'The catalog gives an exact price, but the AI reports a different price.',
    expected: 'Repeat the exact number from the trusted source.',
    failure: 'The AI changes the price from $149 to $199.',
    impact: {
      level: 'High',
      detail:
        'A wrong price, quantity, discount, or delivery time can change a decision.',
    },
    steps: [
      'Read the Nova headphones price from the trusted catalog.',
      'Ask the chatbot for that price.',
      'Compare the number in the answer with the catalog value.',
    ],
    detector: 'Any answer number that differs from the trusted number.',
    failResult: 'NUMERICAL MISMATCH — the AI number does not match the source.',
  },
  {
    id: 'wrong_record',
    name: 'Wrong Record',
    shortName: 'Wrong Record',
    category: 'Record',
    situation: 'AI uses information from a different order or record.',
    whatHappens:
      'The user asks about order DZ-2088, but the AI uses the status from DZ-3190.',
    expected: 'Use only the status attached to the requested order.',
    failure: 'The AI reports processing instead of shipped.',
    impact: {
      level: 'High',
      detail:
        'The answer sounds valid but belongs to the wrong customer record.',
    },
    steps: [
      'Load orders DZ-2088 and DZ-3190.',
      'Ask for the status of DZ-2088.',
      'Check which order supplied the status in the answer.',
      'Flag details taken from another record.',
    ],
    detector:
      'Whether the answer uses facts from the record the user actually requested.',
    failResult:
      'WRONG RECORD — the AI used information from a different order.',
  },
  {
    id: 'policy_mismatch',
    name: 'Policy Mismatch',
    shortName: 'Policy Mismatch',
    category: 'Policy',
    situation: 'AI gives a policy that directly contradicts the real policy.',
    whatHappens:
      'The current electronics return period is 14 days, but the AI states an old 30-day rule.',
    expected: 'Use only the current 14-day return policy.',
    failure: 'The AI promises a 30-day return period.',
    impact: {
      level: 'High',
      detail: 'The business may promise a return it does not offer.',
    },
    steps: [
      'Load the current electronics return policy.',
      'Ask whether an electronic item can be returned after 20 days.',
      'Compare the stated return period with the trusted 14-day rule.',
    ],
    detector:
      'A policy statement that conflicts with the current approved policy.',
    failResult:
      'POLICY MISMATCH — the AI policy contradicts the trusted policy.',
  },
];

export const DEFAULT_SCENARIO: ScenarioId = 'healthy';
export const SCENARIO_KEY = 'shopassist.scenario.v1';
export const SCENARIOS_KEY = 'shopassist.scenarios.v3';
const LEGACY_SCENARIOS_KEY = 'shopassist.scenarios.v2';
export const SCENARIO_IDS: readonly ScenarioId[] = [
  'healthy',
  ...scenarios.map((scenario) => scenario.id),
  'product_information_changed',
  'fake_product_detail',
  'wrong_order_status',
  'policy_hallucination',
  'contradiction_earlier_answer',
  'missing_information',
  'outdated_information',
  'conflicting_sources',
  'unsupported_recommendation',
  'wrong_numerical_answer',
  'entity_mix_up',
  'source_removed',
  'stale_returns',
  'inventory_mismatch',
  'expired_promotion',
  'outdated_warranty',
  'shipping_conflict',
  'recovered',
];

export function getScenarioMode(scenario: ScenarioId): ScenarioMode {
  const aliases: Partial<Record<ScenarioId, ScenarioMode>> = {
    live_data_change: 'inventory_mismatch',
    made_up_detail: 'fake_product_detail',
    wrong_number: 'wrong_numerical_answer',
    wrong_record: 'wrong_order_status',
    policy_mismatch: 'stale_returns',
    product_information_changed: 'inventory_mismatch',
    policy_hallucination: 'stale_returns',
    outdated_information: 'stale_returns',
    conflicting_sources: 'shipping_conflict',
    source_removed: 'expired_promotion',
  };
  return aliases[scenario] ?? (scenario as ScenarioMode);
}

export function normalizeScenarios(value: ScenarioSelection): ScenarioId[] {
  const values = Array.isArray(value) ? value : [value];
  const unique = values.filter(
    (scenario, index): scenario is ScenarioId =>
      isScenarioId(scenario) && values.indexOf(scenario) === index,
  );
  if (!unique.length || unique.includes('healthy')) return ['healthy'];
  if (unique.includes('recovered')) return ['recovered'];
  return unique;
}

export function getScenarioModes(selection: ScenarioSelection): ScenarioMode[] {
  return [...new Set(normalizeScenarios(selection).map(getScenarioMode))];
}

export function hasScenarioMode(
  selection: ScenarioSelection,
  mode: ScenarioMode,
): boolean {
  return getScenarioModes(selection).includes(mode);
}

export function isScenarioId(value: unknown): value is ScenarioId {
  return (
    typeof value === 'string' && SCENARIO_IDS.includes(value as ScenarioId)
  );
}

function migrateScenario(
  value: ScenarioId,
): HallucinationTestId | 'healthy' | 'recovered' {
  if (value === 'healthy' || value === 'recovered') return value;
  if (scenarios.some((scenario) => scenario.id === value))
    return value as HallucinationTestId;
  if (
    value === 'product_information_changed' ||
    value === 'outdated_information' ||
    value === 'contradiction_earlier_answer' ||
    value === 'inventory_mismatch'
  )
    return 'live_data_change';
  if (
    value === 'fake_product_detail' ||
    value === 'missing_information' ||
    value === 'unsupported_recommendation'
  )
    return 'made_up_detail';
  if (value === 'wrong_numerical_answer') return 'wrong_number';
  if (value === 'wrong_order_status' || value === 'entity_mix_up')
    return 'wrong_record';
  return 'policy_mismatch';
}

export function readScenario(): ScenarioId {
  return readScenarios()[0] ?? DEFAULT_SCENARIO;
}

export function writeScenario(value: ScenarioId) {
  writeScenarios([value]);
}

export function readScenarios(): ScenarioId[] {
  if (typeof window === 'undefined') return [DEFAULT_SCENARIO];
  const stored = window.localStorage.getItem(SCENARIOS_KEY);
  if (stored) {
    try {
      const parsed = JSON.parse(stored) as unknown;
      if (Array.isArray(parsed)) {
        const valid = parsed.filter(isScenarioId);
        if (valid.length) return normalizeScenarios(valid);
      }
    } catch {
      // Fall through to migrate the previous saved selection.
    }
  }
  const previous = window.localStorage.getItem(LEGACY_SCENARIOS_KEY);
  if (previous) {
    try {
      const parsed = JSON.parse(previous) as unknown;
      if (Array.isArray(parsed)) {
        const migrated = [
          ...new Set(parsed.filter(isScenarioId).map(migrateScenario)),
        ];
        if (migrated.length) {
          writeScenarios(migrated);
          return normalizeScenarios(migrated);
        }
      }
    } catch {
      // Fall through to the legacy single-scenario value.
    }
  }
  const legacy = window.localStorage.getItem(SCENARIO_KEY);
  return [isScenarioId(legacy) ? migrateScenario(legacy) : DEFAULT_SCENARIO];
}

export function writeScenarios(values: readonly ScenarioId[]) {
  const normalized = normalizeScenarios(values);
  window.localStorage.setItem(SCENARIOS_KEY, JSON.stringify(normalized));
  window.localStorage.setItem(SCENARIO_KEY, normalized[0]);
  window.dispatchEvent(
    new CustomEvent('shopassist:scenario', { detail: normalized }),
  );
}
