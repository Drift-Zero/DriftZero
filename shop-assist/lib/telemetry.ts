import { answerQuestion } from './assistant.ts';
import type { ScenarioId } from './demo-state.ts';

export type ObservedInteraction = { question: string; answer: string; scenario: ScenarioId; citations: string[]; intent: string; latencyMs: number; inputTokens: number; outputTokens: number; status: 'ok' | 'error' };
export type TelemetryDelivery = 'ready' | 'buffered' | 'sent' | 'error';
type Evaluation = ObservedInteraction & { quality: number; groundedness: number; semanticStability: number; temporalStability: number; safety: number; drift: number; reliability: number; latency: number; cost: number; unsupportedClaims: number };

const MINIMUM_WINDOW = 20;
const currentSources = new Set(['catalog-snapshot-2026-09-06', 'returns-policy-v2.1-current', 'electronics-warranty-v3.0', 'shipping-guide-v2.3', 'promotions-ledger-v5.2', 'demo-orders-2026-09-06']);
const factualIntents = new Set(['order_lookup', 'product_search', 'inventory', 'product_detail', 'return_policy', 'refund_policy', 'warranty', 'promotion', 'shipping']);
const bufferedEvaluations: Evaluation[] = [];
const clamp = (value: number) => Math.max(0, Math.min(100, Math.round(value * 10) / 10));
const words = (text: string) => new Set(text.toLowerCase().match(/[a-z0-9]+/g) ?? []);

function similarity(left: string, right: string): number {
  const a = words(left); const b = words(right);
  if (!a.size && !b.size) return 1;
  const intersection = [...a].filter((word) => b.has(word)).length;
  return intersection / Math.max(1, new Set([...a, ...b]).size);
}

export function evaluateInteraction(interaction: ObservedInteraction): Evaluation {
  const expected = answerQuestion(interaction.question, 'healthy');
  const needsEvidence = factualIntents.has(interaction.intent);
  const currentCitationCount = interaction.citations.filter((id) => currentSources.has(id)).length;
  const unsupportedCitationCount = interaction.citations.length - currentCitationCount;
  const missingEvidence = needsEvidence && currentCitationCount === 0 ? 1 : 0;
  const unsupportedClaims = unsupportedCitationCount + missingEvidence;
  const citationScore = needsEvidence ? 100 * currentCitationCount / Math.max(1, interaction.citations.length + missingEvidence) : 100;
  const answerSimilarity = 100 * similarity(interaction.answer, expected.text);
  const groundedness = clamp(citationScore - unsupportedClaims * 20);
  const quality = clamp(answerSimilarity * 0.55 + groundedness * 0.45);
  const semanticStability = clamp(answerSimilarity);
  const temporalStability = clamp(needsEvidence ? citationScore : 100);
  const drift = clamp((groundedness + semanticStability + temporalStability) / 3);
  const safety = /(?:password|credit card|social security|api key)/i.test(interaction.answer) ? 50 : 100;
  const reliability = interaction.status === 'ok' && interaction.answer.trim() ? 100 : 0;
  const latency = clamp(100 - Math.max(0, interaction.latencyMs - 500) / 25);
  const cost = clamp(100 - Math.max(0, interaction.inputTokens + interaction.outputTokens - 500) / 20);
  return { ...interaction, quality, groundedness, semanticStability, temporalStability, safety, drift, reliability, latency, cost, unsupportedClaims };
}

const average = (items: Evaluation[], key: keyof Evaluation) => clamp(items.reduce((sum, item) => sum + Number(item[key]), 0) / items.length);

export function buildTelemetryWindow(items: Evaluation[]) {
  if (items.length < MINIMUM_WINDOW) return null;
  const observedAt = new Date().toISOString();
  return {
    observed_at: observedAt,
    dimensions: { quality: average(items, 'quality'), groundedness: average(items, 'groundedness'), semantic_stability: average(items, 'semanticStability'), temporal_stability: average(items, 'temporalStability'), safety: average(items, 'safety'), drift: average(items, 'drift'), reliability: average(items, 'reliability'), latency: average(items, 'latency'), cost: average(items, 'cost') },
    sample_size: items.length, coverage: 1, source: 'observed',
    traces: items.map((item, index) => ({ occurred_at: observedAt, request_id: `shopassist-${item.scenario}-observed-${Date.now()}-${index}`, question: item.question, answer: item.answer, provider: 'shopassist', status: item.status, latency_ms: item.latencyMs, input_tokens: item.inputTokens, output_tokens: item.outputTokens, cost_usd: 0, retrieved_document_ids: item.citations, citation_count: item.citations.length, unsupported_claim_count: item.unsupportedClaims, groundedness_score: item.groundedness, quality_score: item.quality, safety_flags: item.safety < 100 ? ['sensitive_data'] : [], is_simulated: item.scenario !== 'healthy' && item.scenario !== 'recovered', metadata: { scenario: item.scenario, intent: item.intent, evaluator: 'shopassist-observed-v1' } })),
  };
}

export async function recordInteraction(interaction: ObservedInteraction): Promise<TelemetryDelivery> {
  bufferedEvaluations.push(evaluateInteraction(interaction));
  if (bufferedEvaluations.length < MINIMUM_WINDOW) return 'buffered';
  const batch = bufferedEvaluations.splice(0, MINIMUM_WINDOW);
  const payload = buildTelemetryWindow(batch);
  const apiUrl = (process.env.DRIFTZERO_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
  try {
    const response = await fetch(`${apiUrl}/api/v1/shopassist/telemetry`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload), signal: AbortSignal.timeout(5_000) });
    if (!response.ok) { bufferedEvaluations.unshift(...batch); return 'error'; }
    return 'sent';
  } catch { bufferedEvaluations.unshift(...batch); return 'error'; }
}

export function resetTelemetryBufferForTests() { bufferedEvaluations.length = 0; }
