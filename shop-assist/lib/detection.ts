import { answerQuestion, type ConversationContext } from './assistant.ts';
import {
  hasScenarioMode,
  normalizeScenarios,
  type ScenarioId,
  type ScenarioSelection,
} from './demo-state.ts';

export type DetectorStatus = 'PASS' | 'WARNING' | 'FAIL';
export type DetectorCheckResult = {
  id: string;
  name: string;
  status: DetectorStatus;
  detail: string;
};
export type DetectionReport = {
  observedAt: string;
  scenarios: ScenarioId[];
  sourceSnapshot: {
    validFrom: string;
    validUntil: string | null;
    source: string;
  };
  checks: DetectorCheckResult[];
  overall: {
    status: DetectorStatus;
    title: string;
    aiClaim: string;
    trustedSource: string;
  };
};

type HistoryEntry = { role: 'user' | 'assistant'; text: string };

const DETECTION_KEY = 'shopassist.latest-detection.v1';
const words = (text: string) =>
  new Set(text.toLowerCase().match(/[a-z0-9]+/g) ?? []);

function similarity(left: string, right: string): number {
  const a = words(left);
  const b = words(right);
  if (!a.size && !b.size) return 1;
  const overlap = [...a].filter((word) => b.has(word)).length;
  return overlap / Math.max(1, new Set([...a, ...b]).size);
}

function numbers(text: string): string[] {
  return (text.match(/(?:[$₹])?\d+(?:[.,]\d+)?%?/g) ?? []).map((value) =>
    value.replace(/,/g, ''),
  );
}

function categoricalFacts(text: string): string[] {
  const value = text.toLowerCase();
  const facts: string[] = [];
  if (/\bsold out\b/.test(value)) facts.push('sold_out');
  if (/\b(?:in stock|available)\b/.test(value)) facts.push('available');
  if (/\bprocessing\b/.test(value)) facts.push('processing');
  if (/\bshipped\b/.test(value)) facts.push('shipped');
  if (/\bdelivered\b/.test(value)) facts.push('delivered');
  if (/\bcancelled?\b/.test(value)) facts.push('cancelled');
  return facts;
}

function refusesUnknown(text: string): boolean {
  return /\b(?:cannot|can.t|do not have|don.t have|not available|unable to verify|no information|sorry.*information)\b/i.test(
    text,
  );
}

function conversationContext(history: HistoryEntry[]): ConversationContext {
  const turns: NonNullable<ConversationContext['turns']> = [];
  let question = '';
  for (const entry of history) {
    if (entry.role === 'user') {
      question = entry.text;
      continue;
    }
    turns.push({ question, answer: entry.text, intent: 'history' });
    question = '';
  }
  return { turns };
}

export function getRelevantDetectorChecks(
  selection: ScenarioSelection,
): string[] {
  const scenarios = normalizeScenarios(selection);
  const checks = new Set<string>(['Source Grounding']);
  if (
    hasScenarioMode(scenarios, 'inventory_mismatch') ||
    hasScenarioMode(scenarios, 'stale_returns') ||
    hasScenarioMode(scenarios, 'expired_promotion') ||
    hasScenarioMode(scenarios, 'wrong_order_status')
  ) {
    checks.add('Temporal Freshness');
  }
  if (
    hasScenarioMode(scenarios, 'wrong_numerical_answer') ||
    hasScenarioMode(scenarios, 'inventory_mismatch')
  ) {
    checks.add('Numerical Accuracy');
  }
  if (
    hasScenarioMode(scenarios, 'contradiction_earlier_answer') ||
    hasScenarioMode(scenarios, 'inventory_mismatch') ||
    hasScenarioMode(scenarios, 'stale_returns') ||
    hasScenarioMode(scenarios, 'expired_promotion')
  ) {
    checks.add('Consistency');
  }
  if (
    hasScenarioMode(scenarios, 'entity_mix_up') ||
    hasScenarioMode(scenarios, 'wrong_order_status')
  ) {
    checks.add('Entity Accuracy');
  }
  if (
    hasScenarioMode(scenarios, 'fake_product_detail') ||
    hasScenarioMode(scenarios, 'missing_information') ||
    hasScenarioMode(scenarios, 'unsupported_recommendation') ||
    hasScenarioMode(scenarios, 'stale_returns') ||
    hasScenarioMode(scenarios, 'outdated_warranty') ||
    hasScenarioMode(scenarios, 'expired_promotion')
  ) {
    checks.add('Unsupported Claims');
  }
  if (hasScenarioMode(scenarios, 'shipping_conflict')) {
    checks.add('Source Agreement');
  }
  return [...checks];
}

export function buildDetectionReport(input: {
  question: string;
  answer: string;
  citations: string[];
  scenarios: ScenarioSelection;
  history?: HistoryEntry[];
}): DetectionReport {
  const observedAt = new Date().toISOString();
  const scenarios = normalizeScenarios(input.scenarios);
  // Build the trusted answer from the source state valid at response time. A
  // product-information update is a legitimate source change, so keep that
  // source update while stripping model-only fault injections. Earlier answers
  // are never the source of truth.
  const sourceChangeScenarios = scenarios.filter(
    (scenario) =>
      scenario === 'live_data_change' ||
      scenario === 'product_information_changed' ||
      scenario === 'inventory_mismatch',
  );
  const trusted = answerQuestion(
    input.question,
    sourceChangeScenarios.length ? sourceChangeScenarios : 'healthy',
    conversationContext(input.history ?? []),
  );
  const answerSimilarity = similarity(input.answer, trusted.text);
  const sameNumbers =
    JSON.stringify(numbers(input.answer)) ===
    JSON.stringify(numbers(trusted.text));
  const sameCategoricalFacts =
    JSON.stringify(categoricalFacts(input.answer)) ===
    JSON.stringify(categoricalFacts(trusted.text));
  const hasEvidence =
    trusted.citations.length === 0 ||
    trusted.citations.every((citation) =>
      input.citations.includes(citation.id),
    );
  const answerMatchesCurrentSource =
    sameNumbers &&
    sameCategoricalFacts &&
    (answerSimilarity >= 0.42 ||
      ((numbers(trusted.text).length > 0 ||
        categoricalFacts(trusted.text).length > 0) &&
        answerSimilarity >= 0.15) ||
      (refusesUnknown(input.answer) && refusesUnknown(trusted.text)));
  const previousAnswer = [...(input.history ?? [])]
    .reverse()
    .find((entry) => entry.role === 'assistant')?.text;
  const sourceChangeWasSimulated =
    hasScenarioMode(scenarios, 'inventory_mismatch') ||
    hasScenarioMode(scenarios, 'stale_returns') ||
    hasScenarioMode(scenarios, 'expired_promotion') ||
    hasScenarioMode(scenarios, 'wrong_order_status');

  // In a real deployment no scenario picker is required: infer extra checks
  // from the actual interaction as well as the demo situations.
  const checkNames = new Set(getRelevantDetectorChecks(scenarios));
  const numericIntent =
    /(price|cost|how much|stock|available|quantity|discount|percent|percentage|limit|days|return period)/i.test(
      input.question,
    );
  if (numericIntent) checkNames.add('Numerical Accuracy');
  if (
    /(price|stock|available|availability|delivery|order|return|refund|warranty|promotion|discount)/i.test(
      input.question,
    )
  ) {
    checkNames.add('Temporal Freshness');
  }
  if (previousAnswer) checkNames.add('Consistency');
  const checks = [...checkNames].map<DetectorCheckResult>((name) => {
    if (name === 'Source Grounding') {
      const conflictAcknowledged =
        hasScenarioMode(scenarios, 'shipping_conflict') &&
        /\b(?:conflict|disagree|different|one source|another source|sources)\b/i.test(
          input.answer,
        );
      const pass = hasEvidence && answerMatchesCurrentSource;
      return {
        id: 'source-grounding',
        name,
        status: pass ? 'PASS' : conflictAcknowledged ? 'WARNING' : 'FAIL',
        detail: pass
          ? 'The answer matches the trusted source valid for this response.'
          : conflictAcknowledged
            ? 'The answer includes multiple source values; review the conflict result below.'
            : 'The answer is not fully supported by the trusted source snapshot.',
      };
    }
    if (name === 'Temporal Freshness') {
      return {
        id: 'temporal-freshness',
        name,
        status: answerMatchesCurrentSource ? 'PASS' : 'FAIL',
        detail: answerMatchesCurrentSource
          ? 'The answer uses the source value valid at response time.'
          : 'The answer does not match the source value valid at response time.',
      };
    }
    if (name === 'Numerical Accuracy') {
      return {
        id: 'numerical-accuracy',
        name,
        status: sameNumbers ? 'PASS' : 'FAIL',
        detail: sameNumbers
          ? 'The numerical values match the trusted source.'
          : `Answer values ${numbers(input.answer).join(', ') || 'none'} do not match ${numbers(trusted.text).join(', ') || 'the trusted value'}.`,
      };
    }
    if (name === 'Consistency') {
      if (!previousAnswer) {
        return {
          id: 'consistency',
          name,
          status: hasScenarioMode(scenarios, 'contradiction_earlier_answer')
            ? 'WARNING'
            : 'PASS',
          detail: hasScenarioMode(scenarios, 'contradiction_earlier_answer')
            ? 'Ask the same question again to compare the two answers.'
            : 'There is no earlier answer to contradict in this interaction.',
        };
      }
      const answerChanged = similarity(previousAnswer, input.answer) < 0.8;
      const justified =
        !answerChanged ||
        (sourceChangeWasSimulated && answerMatchesCurrentSource);
      return {
        id: 'consistency',
        name,
        status: justified ? 'PASS' : 'WARNING',
        detail: justified
          ? answerChanged
            ? 'The answer changed because the trusted source changed.'
            : 'The answer remains consistent with the earlier response.'
          : 'The answer changed without support from the current source.',
      };
    }
    if (name === 'Entity Accuracy') {
      return {
        id: 'entity-accuracy',
        name,
        status: answerMatchesCurrentSource ? 'PASS' : 'FAIL',
        detail: answerMatchesCurrentSource
          ? 'The answer uses details from the correct record.'
          : 'The answer appears to mix details from another record.',
      };
    }
    if (name === 'Source Agreement') {
      const acknowledged =
        /\b(?:conflict|disagree|different|one source|another source|sources)\b/i.test(
          input.answer,
        );
      return {
        id: 'source-agreement',
        name,
        status: acknowledged ? 'PASS' : 'FAIL',
        detail: acknowledged
          ? 'The answer clearly flags that the trusted sources disagree.'
          : 'Trusted sources disagree, so the assistant should flag the conflict instead of choosing silently.',
      };
    }
    return {
      id: 'unsupported-claims',
      name,
      status: answerMatchesCurrentSource ? 'PASS' : 'FAIL',
      detail: answerMatchesCurrentSource
        ? 'No unsupported claim was found.'
        : 'At least one claim cannot be verified in the trusted source.',
    };
  });

  const status: DetectorStatus = checks.some((check) => check.status === 'FAIL')
    ? 'FAIL'
    : checks.some((check) => check.status === 'WARNING')
      ? 'WARNING'
      : 'PASS';
  const failureTitle = scenarios.includes('wrong_number')
    ? 'NUMERICAL MISMATCH'
    : scenarios.includes('wrong_record')
      ? 'WRONG RECORD'
      : scenarios.includes('policy_mismatch')
        ? 'POLICY MISMATCH'
        : scenarios.includes('made_up_detail')
          ? 'UNSUPPORTED CLAIM'
          : scenarios.includes('live_data_change')
            ? 'STALE'
            : 'Unsupported claim detected';
  const passTitle =
    scenarios.includes('live_data_change') && previousAnswer
      ? 'SUPPORTED — source changed, so the new answer is valid'
      : 'SUPPORTED — the claim matches the trusted source';

  return {
    observedAt,
    scenarios,
    sourceSnapshot: {
      validFrom: observedAt,
      validUntil: null,
      source:
        trusted.citations.map((citation) => citation.label).join(', ') ||
        'ShopAssist trusted knowledge',
    },
    checks,
    overall: {
      status,
      title:
        status === 'PASS'
          ? passTitle
          : status === 'WARNING'
            ? 'The answer needs review'
            : failureTitle,
      aiClaim: input.answer,
      trustedSource: trusted.text,
    },
  };
}

export function readDetectionReport(): DetectionReport | null {
  if (typeof window === 'undefined') return null;
  try {
    const value = window.localStorage.getItem(DETECTION_KEY);
    return value ? (JSON.parse(value) as DetectionReport) : null;
  } catch {
    return null;
  }
}

export function writeDetectionReport(report: DetectionReport): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(DETECTION_KEY, JSON.stringify(report));
  window.dispatchEvent(
    new CustomEvent('shopassist:detection', { detail: report }),
  );
}

export function clearDetectionReport(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(DETECTION_KEY);
  window.dispatchEvent(
    new CustomEvent('shopassist:detection', { detail: null }),
  );
}
