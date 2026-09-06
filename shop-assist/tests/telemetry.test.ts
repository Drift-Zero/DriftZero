import assert from 'node:assert/strict';
import test from 'node:test';

import { answerQuestion } from '../lib/assistant.ts';
import { buildTelemetryWindow, evaluateInteraction } from '../lib/telemetry.ts';

function observed(question: string, scenario: 'healthy' | 'stale_returns') {
  const answer = answerQuestion(question, scenario);
  return evaluateInteraction({
    question,
    answer: answer.text,
    scenario,
    citations: answer.citations.map((citation) => citation.id),
    intent: answer.intent,
    latencyMs: 240,
    inputTokens: 80,
    outputTokens: 40,
    status: 'ok',
  });
}

void test('scores are derived from the observed answer and its citations', () => {
  const healthy = observed('Can I return headphones after 20 days?', 'healthy');
  const stale = observed('Can I return headphones after 20 days?', 'stale_returns');

  assert.equal(healthy.groundedness, 100);
  assert.ok(stale.groundedness < healthy.groundedness);
  assert.ok(stale.quality < healthy.quality);
  assert.ok(stale.drift < healthy.drift);
});

void test('does not create a telemetry window below the 20 sample gate', () => {
  const evaluations = Array.from({ length: 19 }, () => observed('What is your return policy?', 'healthy'));
  assert.equal(buildTelemetryWindow(evaluations), null);
});

void test('builds an observed window from 20 real interaction evaluations', () => {
  const evaluations = Array.from({ length: 20 }, () => observed('What is your return policy?', 'healthy'));
  const window = buildTelemetryWindow(evaluations);

  assert.equal(window?.sample_size, 20);
  assert.equal(window?.source, 'observed');
  assert.equal(window?.traces.length, 20);
  assert.equal(window?.dimensions.groundedness, 100);
  assert.equal(window?.traces[0]?.metadata.evaluator, 'shopassist-observed-v1');
});
