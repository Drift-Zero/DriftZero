import assert from 'node:assert/strict';
import test from 'node:test';

import { answerQuestion } from '../lib/assistant.ts';
import {
  buildTelemetryWindow,
  evaluateInteraction,
  recordInteraction,
  resetTelemetryBufferForTests,
} from '../lib/telemetry.ts';

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
  const stale = observed(
    'Can I return headphones after 20 days?',
    'stale_returns',
  );

  assert.equal(healthy.groundedness, 100);
  assert.ok(stale.groundedness < healthy.groundedness);
  assert.ok(stale.quality < healthy.quality);
  assert.ok(stale.drift < healthy.drift);
});

void test('does not create a telemetry window below the 20 sample gate', () => {
  const evaluations = Array.from({ length: 19 }, () =>
    observed('What is your return policy?', 'healthy'),
  );
  assert.equal(buildTelemetryWindow(evaluations), null);
});

void test('builds an observed window from 20 real interaction evaluations', () => {
  const evaluations = Array.from({ length: 20 }, () =>
    observed('What is your return policy?', 'healthy'),
  );
  const window = buildTelemetryWindow(evaluations);

  assert.equal(window?.sample_size, 20);
  assert.equal(window?.source, 'observed');
  assert.equal(window?.traces.length, 20);
  assert.equal(window?.dimensions.groundedness, 100);
  assert.equal(window?.traces[0]?.metadata.evaluator, 'shopassist-observed-v1');
});

void test('sends raw Groq interactions to DriftZero for authoritative evaluation', async () => {
  resetTelemetryBufferForTests();
  const originalFetch = globalThis.fetch;
  const previousModelId = process.env.DRIFTZERO_MODEL_ID;
  process.env.DRIFTZERO_MODEL_ID = 'configured-model-id';
  let requestUrl = '';
  let requestBody: Record<string, unknown> | undefined;
  globalThis.fetch = async (input, init) => {
    requestUrl =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const body = init?.body;
    if (typeof body !== 'string')
      throw new Error('Expected a JSON request body');
    requestBody = JSON.parse(body) as Record<string, unknown>;
    return new Response('{}', { status: 201 });
  };
  try {
    for (let index = 0; index < 20; index += 1) {
      const delivery = await recordInteraction({
        requestId: `groq-interaction-${index}`,
        occurredAt: `2026-09-13T00:00:${String(index).padStart(2, '0')}Z`,
        question: 'What is the price of AeroBuds?',
        answer: 'AeroBuds cost $79.',
        provider: 'groq',
        modelName: 'openai/gpt-oss-120b',
        scenarios: ['healthy'],
        citations: ['catalog-snapshot-2026-09-06'],
        intent: 'product_detail',
        latencyMs: 420,
        inputTokens: 90,
        outputTokens: 18,
        status: 'ok',
        isSimulated: false,
      });
      assert.equal(delivery, index === 19 ? 'sent' : 'buffered');
    }

    assert.equal(
      requestUrl,
      'http://127.0.0.1:8000/api/v1/models/configured-model-id/interactions/evaluate',
    );
    assert.ok(requestBody);
    assert.equal('dimensions' in requestBody, false);
    assert.equal(requestBody.source, 'observed');
    const interactions = requestBody.interactions as Array<
      Record<string, unknown>
    >;
    assert.equal(interactions.length, 20);
    assert.equal(interactions[0]?.request_id, 'groq-interaction-0');
    assert.equal(interactions[0]?.answer, 'AeroBuds cost $79.');
    assert.equal(interactions[0]?.provider, 'groq');
    assert.equal(interactions[0]?.model_name, 'openai/gpt-oss-120b');
    assert.equal(interactions[0]?.input_tokens, 90);
    assert.equal(interactions[0]?.output_tokens, 18);
    assert.equal(interactions[0]?.is_simulated, false);
  } finally {
    globalThis.fetch = originalFetch;
    if (previousModelId === undefined) delete process.env.DRIFTZERO_MODEL_ID;
    else process.env.DRIFTZERO_MODEL_ID = previousModelId;
    resetTelemetryBufferForTests();
  }
});

void test('resolves the unique ShopAssist model when no model ID is configured', async () => {
  resetTelemetryBufferForTests();
  const originalFetch = globalThis.fetch;
  const previousModelId = process.env.DRIFTZERO_MODEL_ID;
  delete process.env.DRIFTZERO_MODEL_ID;
  const urls: string[] = [];
  globalThis.fetch = async (input) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    urls.push(url);
    if (url.endsWith('/api/v1/models')) {
      return Response.json([
        { id: 'resolved-shopassist-id', name: 'ShopAssist' },
      ]);
    }
    return new Response('{}', { status: 201 });
  };
  try {
    for (let index = 0; index < 20; index += 1) {
      await recordInteraction({
        requestId: `resolved-${index}`,
        question: 'What products are available?',
        answer: 'Several products are available.',
        provider: 'groq',
        modelName: 'openai/gpt-oss-120b',
        scenarios: ['healthy'],
        citations: [],
        intent: 'product_search',
        latencyMs: 300,
        inputTokens: 70,
        outputTokens: 12,
        status: 'ok',
        isSimulated: false,
      });
    }

    assert.deepEqual(urls, [
      'http://127.0.0.1:8000/api/v1/models',
      'http://127.0.0.1:8000/api/v1/models/resolved-shopassist-id/interactions/evaluate',
    ]);
  } finally {
    globalThis.fetch = originalFetch;
    if (previousModelId === undefined) delete process.env.DRIFTZERO_MODEL_ID;
    else process.env.DRIFTZERO_MODEL_ID = previousModelId;
    resetTelemetryBufferForTests();
  }
});

void test('keeps explicit demo failures separate from observed real traffic', async () => {
  resetTelemetryBufferForTests();
  const originalFetch = globalThis.fetch;
  const previousModelId = process.env.DRIFTZERO_MODEL_ID;
  process.env.DRIFTZERO_MODEL_ID = 'configured-model-id';
  let requestBody: Record<string, unknown> | undefined;
  globalThis.fetch = async (_input, init) => {
    const body = init?.body;
    if (typeof body !== 'string')
      throw new Error('Expected a JSON request body');
    requestBody = JSON.parse(body) as Record<string, unknown>;
    return new Response('{}', { status: 201 });
  };
  try {
    for (let index = 0; index < 20; index += 1) {
      await recordInteraction({
        requestId: `simulated-${index}`,
        question: 'How many Nova ANC Headphones are available?',
        answer: 'There are 99 Nova ANC Headphones available.',
        provider: 'groq',
        modelName: 'openai/gpt-oss-120b',
        scenarios: ['inventory_mismatch'],
        citations: ['catalog-snapshot-2026-09-06'],
        intent: 'inventory',
        latencyMs: 300,
        inputTokens: 70,
        outputTokens: 12,
        status: 'ok',
        isSimulated: true,
      });
    }

    assert.equal(requestBody?.source, 'simulated');
    const interactions = requestBody?.interactions as Array<
      Record<string, unknown>
    >;
    assert.equal(interactions[0]?.is_simulated, true);
    assert.equal('dimensions' in (requestBody ?? {}), false);
  } finally {
    globalThis.fetch = originalFetch;
    if (previousModelId === undefined) delete process.env.DRIFTZERO_MODEL_ID;
    else process.env.DRIFTZERO_MODEL_ID = previousModelId;
    resetTelemetryBufferForTests();
  }
});
