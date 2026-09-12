import { randomUUID } from 'node:crypto';

import { answerQuestion } from './assistant.ts';
import { normalizeScenarios, type ScenarioId } from './demo-state.ts';

export type ObservedInteraction = {
  requestId?: string;
  occurredAt?: string;
  question: string;
  answer: string;
  provider?: string;
  modelName?: string;
  scenario?: ScenarioId;
  scenarios?: ScenarioId[];
  citations: string[];
  intent: string;
  latencyMs: number;
  inputTokens: number;
  outputTokens: number;
  status: 'ok' | 'error';
  errorCode?: string;
  isSimulated?: boolean;
};
export type TelemetryDelivery = 'ready' | 'buffered' | 'sent' | 'error';
type Evaluation = ObservedInteraction & {
  quality: number;
  groundedness: number;
  semanticStability: number;
  temporalStability: number;
  safety: number;
  drift: number;
  reliability: number;
  latency: number;
  cost: number;
  unsupportedClaims: number;
};

const MINIMUM_WINDOW = 20;
const currentSources = new Set([
  'catalog-snapshot-2026-09-06',
  'returns-policy-v2.1-current',
  'electronics-warranty-v3.0',
  'shipping-guide-v2.3',
  'promotions-ledger-v5.2',
  'demo-orders-2026-09-06',
]);
const factualIntents = new Set([
  'order_lookup',
  'product_search',
  'inventory',
  'product_detail',
  'return_policy',
  'refund_policy',
  'warranty',
  'promotion',
  'shipping',
]);
const bufferedEvaluations: Evaluation[] = [];
const bufferedInteractions: ObservedInteraction[] = [];
let resolvedModelId: string | undefined;
const clamp = (value: number) =>
  Math.max(0, Math.min(100, Math.round(value * 10) / 10));
const words = (text: string) =>
  new Set(text.toLowerCase().match(/[a-z0-9]+/g) ?? []);

function similarity(left: string, right: string): number {
  const a = words(left);
  const b = words(right);
  if (!a.size && !b.size) return 1;
  const intersection = [...a].filter((word) => b.has(word)).length;
  return intersection / Math.max(1, new Set([...a, ...b]).size);
}

/** Legacy deterministic scorer retained only for explicit simulation fixtures. */
export function evaluateInteraction(
  interaction: ObservedInteraction,
): Evaluation {
  const expected = answerQuestion(interaction.question, 'healthy');
  const needsEvidence = factualIntents.has(interaction.intent);
  const currentCitationCount = interaction.citations.filter((id) =>
    currentSources.has(id),
  ).length;
  const unsupportedCitationCount =
    interaction.citations.length - currentCitationCount;
  const missingEvidence = needsEvidence && currentCitationCount === 0 ? 1 : 0;
  const unsupportedClaims = unsupportedCitationCount + missingEvidence;
  const citationScore = needsEvidence
    ? (100 * currentCitationCount) /
      Math.max(1, interaction.citations.length + missingEvidence)
    : 100;
  const answerSimilarity = 100 * similarity(interaction.answer, expected.text);
  const groundedness = clamp(citationScore - unsupportedClaims * 20);
  const quality = clamp(answerSimilarity * 0.55 + groundedness * 0.45);
  const semanticStability = clamp(answerSimilarity);
  const temporalStability = clamp(needsEvidence ? citationScore : 100);
  const drift = clamp(
    (groundedness + semanticStability + temporalStability) / 3,
  );
  const safety = /(?:password|credit card|social security|api key)/i.test(
    interaction.answer,
  )
    ? 50
    : 100;
  const reliability =
    interaction.status === 'ok' && interaction.answer.trim() ? 100 : 0;
  const latency = clamp(100 - Math.max(0, interaction.latencyMs - 500) / 25);
  const cost = clamp(
    100 -
      Math.max(0, interaction.inputTokens + interaction.outputTokens - 500) /
        20,
  );
  return {
    ...interaction,
    quality,
    groundedness,
    semanticStability,
    temporalStability,
    safety,
    drift,
    reliability,
    latency,
    cost,
    unsupportedClaims,
  };
}

const average = (items: Evaluation[], key: keyof Evaluation) =>
  clamp(items.reduce((sum, item) => sum + Number(item[key]), 0) / items.length);

export function buildTelemetryWindow(items: Evaluation[]) {
  if (items.length < MINIMUM_WINDOW) return null;
  const observedAt = new Date().toISOString();
  return {
    observed_at: observedAt,
    dimensions: {
      quality: average(items, 'quality'),
      groundedness: average(items, 'groundedness'),
      semantic_stability: average(items, 'semanticStability'),
      temporal_stability: average(items, 'temporalStability'),
      safety: average(items, 'safety'),
      drift: average(items, 'drift'),
      reliability: average(items, 'reliability'),
      latency: average(items, 'latency'),
      cost: average(items, 'cost'),
    },
    sample_size: items.length,
    coverage: 1,
    source: 'observed',
    traces: items.map((item, index) => {
      const scenarios = normalizeScenarios(
        item.scenarios ?? item.scenario ?? 'healthy',
      );
      return {
        occurred_at: observedAt,
        request_id: `shopassist-${scenarios.join('-')}-observed-${Date.now()}-${index}`,
        question: item.question,
        answer: item.answer,
        provider: 'shopassist',
        status: item.status,
        latency_ms: item.latencyMs,
        input_tokens: item.inputTokens,
        output_tokens: item.outputTokens,
        cost_usd: 0,
        retrieved_document_ids: item.citations,
        citation_count: item.citations.length,
        unsupported_claim_count: item.unsupportedClaims,
        groundedness_score: item.groundedness,
        quality_score: item.quality,
        safety_flags: item.safety < 100 ? ['sensitive_data'] : [],
        is_simulated: scenarios.some(
          (scenario) => scenario !== 'healthy' && scenario !== 'recovered',
        ),
        metadata: {
          scenarios,
          scenario: scenarios[0],
          intent: item.intent,
          evaluator: 'shopassist-observed-v1',
        },
      };
    }),
  };
}

export async function recordInteraction(
  interaction: ObservedInteraction,
): Promise<TelemetryDelivery> {
  bufferedInteractions.push(interaction);
  if (bufferedInteractions.length < MINIMUM_WINDOW) return 'buffered';
  const batch = bufferedInteractions.splice(0, MINIMUM_WINDOW);
  const apiUrl = (
    process.env.DRIFTZERO_API_URL ?? 'http://127.0.0.1:8000'
  ).replace(/\/$/, '');
  try {
    const modelId = await resolveDriftZeroModelId(apiUrl);
    const ingestionKey = process.env.DRIFTZERO_INGEST_KEY?.trim();
    const response = await fetch(
      `${apiUrl}/api/v1/models/${encodeURIComponent(modelId)}/interactions/evaluate`,
      {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          ...(ingestionKey ? { 'X-DriftZero-Ingest-Key': ingestionKey } : {}),
        },
        body: JSON.stringify({
          event_id: `shopassist:${randomUUID()}`,
          interactions: batch.map((item) => ({
            request_id: item.requestId ?? `shopassist:${randomUUID()}`,
            occurred_at: item.occurredAt ?? new Date().toISOString(),
            question: item.question,
            answer: item.answer,
            provider: item.provider,
            model_name: item.modelName,
            status: item.status,
            error_code: item.errorCode,
            latency_ms: item.latencyMs,
            input_tokens: item.inputTokens,
            output_tokens: item.outputTokens,
            is_simulated: item.isSimulated ?? false,
          })),
          source: batch.some((item) => item.isSimulated)
            ? 'simulated'
            : 'observed',
          actor: 'shopassist-connector',
        }),
        signal: AbortSignal.timeout(5_000),
      },
    );
    if (!response.ok) {
      bufferedInteractions.unshift(...batch);
      console.error(
        JSON.stringify({
          event: 'shopassist.monitoring.failed',
          status: response.status,
        }),
      );
      return 'error';
    }
    console.info(
      JSON.stringify({
        event: 'shopassist.monitoring.sent',
        sample_size: batch.length,
      }),
    );
    return 'sent';
  } catch (error) {
    bufferedInteractions.unshift(...batch);
    console.error(
      JSON.stringify({
        event: 'shopassist.monitoring.failed',
        error_type: error instanceof Error ? error.name : 'UnknownError',
      }),
    );
    return 'error';
  }
}

async function resolveDriftZeroModelId(apiUrl: string): Promise<string> {
  const configured = process.env.DRIFTZERO_MODEL_ID?.trim();
  if (configured) return configured;
  if (resolvedModelId) return resolvedModelId;
  const response = await fetch(`${apiUrl}/api/v1/models`, {
    headers: { accept: 'application/json' },
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok)
    throw new Error(
      `DriftZero model lookup failed with status ${response.status}`,
    );
  const models = (await response.json()) as unknown;
  if (!Array.isArray(models))
    throw new Error('DriftZero model lookup returned an invalid response');
  const matches = models.filter((item): item is { id: string; name: string } =>
    Boolean(
      item &&
      typeof item === 'object' &&
      'id' in item &&
      'name' in item &&
      item.name === 'ShopAssist' &&
      typeof item.id === 'string',
    ),
  );
  if (matches.length !== 1)
    throw new Error('DriftZero requires exactly one ShopAssist model');
  resolvedModelId = matches[0].id;
  return resolvedModelId;
}

export function resetTelemetryBufferForTests() {
  bufferedEvaluations.length = 0;
  bufferedInteractions.length = 0;
  resolvedModelId = undefined;
}
