import assert from 'node:assert/strict';
import test from 'node:test';

import { POST } from '../app/api/chat/route.ts';
import { resetTelemetryBufferForTests } from '../lib/telemetry.ts';

void test('monitoring failure does not replace a successful Groq answer', async () => {
  resetTelemetryBufferForTests();
  const originalFetch = globalThis.fetch;
  const previousGroqKey = process.env.GROQ_API_KEY;
  const previousModelId = process.env.DRIFTZERO_MODEL_ID;
  process.env.GROQ_API_KEY = 'unit-test-key';
  process.env.DRIFTZERO_MODEL_ID = 'shopassist-model';
  let monitoringPayload: Record<string, unknown> | undefined;
  globalThis.fetch = async (input, init) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    if (url.includes('api.groq.com')) {
      return Response.json({
        id: `groq-request-${Math.random()}`,
        model: 'openai/gpt-oss-120b',
        choices: [
          {
            finish_reason: 'stop',
            message: {
              content: JSON.stringify({
                answer: 'AeroBuds cost $79.',
                source_ids: ['catalog-snapshot-2026-09-06'],
              }),
            },
          },
        ],
        usage: { prompt_tokens: 90, completion_tokens: 18 },
      });
    }
    const body = init?.body;
    if (typeof body !== 'string')
      throw new Error('Expected a JSON request body');
    monitoringPayload = JSON.parse(body) as Record<string, unknown>;
    return new Response('{}', { status: 503 });
  };

  try {
    let finalPayload: Record<string, unknown> | undefined;
    for (let index = 0; index < 20; index += 1) {
      const response = await POST(
        new Request('http://shopassist.test/api/chat', {
          method: 'POST',
          body: JSON.stringify({
            message: 'What is the price of AeroBuds?',
            history: [],
            scenarios: ['healthy'],
          }),
        }),
      );
      assert.equal(response.status, 200);
      finalPayload = (await response.json()) as Record<string, unknown>;
    }

    assert.equal(finalPayload?.answer, 'AeroBuds cost $79.');
    assert.equal(finalPayload?.model, 'openai/gpt-oss-120b');
    assert.equal(finalPayload?.telemetry, 'error');
    assert.equal('providerError' in (finalPayload ?? {}), false);
    assert.ok(monitoringPayload);
    const interactions = monitoringPayload.interactions as Array<
      Record<string, unknown>
    >;
    assert.equal(interactions[0]?.answer, 'AeroBuds cost $79.');
    assert.equal(interactions[0]?.provider, 'groq');
    assert.equal(interactions[0]?.model_name, 'openai/gpt-oss-120b');
    assert.equal(interactions[0]?.is_simulated, false);
  } finally {
    globalThis.fetch = originalFetch;
    if (previousGroqKey === undefined) delete process.env.GROQ_API_KEY;
    else process.env.GROQ_API_KEY = previousGroqKey;
    if (previousModelId === undefined) delete process.env.DRIFTZERO_MODEL_ID;
    else process.env.DRIFTZERO_MODEL_ID = previousModelId;
    resetTelemetryBufferForTests();
  }
});
