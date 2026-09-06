export type TelemetryDelivery = 'ready' | 'buffered' | 'sent' | 'error';

import type { ScenarioId } from './demo-state.ts';

type Interaction = {
  question: string;
  answer: string;
  scenario: ScenarioId;
  citations: string[];
  confidence: number;
  groundedness: number;
  unsupportedClaims: number;
  intent: string;
};

const BUFFER_KEY = 'shopassist.telemetry.v1';

function buffer(payload: object) {
  try {
    const current = JSON.parse(sessionStorage.getItem(BUFFER_KEY) ?? '[]') as object[];
    sessionStorage.setItem(BUFFER_KEY, JSON.stringify([...current.slice(-99), payload]));
  } catch {
    // Demo telemetry should never prevent the customer-facing answer.
  }
}

export async function sendInteractionTelemetry(interaction: Interaction): Promise<TelemetryDelivery> {
  const apiUrl = process.env.NEXT_PUBLIC_DRIFTZERO_API_URL?.replace(/\/$/, '');
  const modelId = process.env.NEXT_PUBLIC_DRIFTZERO_MODEL_ID;
  const observedAt = new Date().toISOString();
  const degraded = interaction.scenario !== 'healthy' && interaction.scenario !== 'recovered';

  const payload = {
    observed_at: observedAt,
    dimensions: {
      quality: degraded ? 48 : 96,
      groundedness: interaction.groundedness,
      semantic_stability: degraded ? 44 : 97,
      temporal_stability: degraded ? 40 : 98,
      safety: 99,
      drift: degraded ? 35 : 98,
      reliability: 99,
      latency: 97,
      cost: 96,
    },
    sample_size: 1,
    coverage: 1,
    source: 'simulated',
    traces: [
      {
        occurred_at: observedAt,
        request_id: `shopassist-${interaction.scenario}-${Date.now()}`,
        question: interaction.question,
        answer: interaction.answer,
        provider: 'shopassist-demo-adapter',
        status: 'ok',
        latency_ms: degraded ? 184 : 126,
        input_tokens: Math.max(8, Math.round(interaction.question.length / 4)),
        output_tokens: Math.max(12, Math.round(interaction.answer.length / 4)),
        cost_usd: 0,
        retrieved_document_ids: interaction.citations,
        citation_count: interaction.citations.length,
        unsupported_claim_count: interaction.unsupportedClaims,
        groundedness_score: interaction.groundedness,
        quality_score: degraded ? 48 : 96,
        safety_flags: [],
        is_simulated: true,
        metadata: { scenario: interaction.scenario, intent: interaction.intent, confidence: interaction.confidence },
      },
    ],
  };

  buffer(payload);
  if (!apiUrl || !modelId) return 'buffered';

  try {
    const response = await fetch(`${apiUrl}/api/v1/models/${modelId}/telemetry`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return response.ok ? 'sent' : 'error';
  } catch {
    return 'error';
  }
}
