import assert from 'node:assert/strict';
import test from 'node:test';

import { POST } from '../app/api/chat/route.ts';
import {
  resetActiveScenarios,
  setActiveScenarios,
} from '../lib/server-scenario-state.ts';
import { resetTelemetryBufferForTests } from '../lib/telemetry.ts';

void test('monitoring failure does not replace a successful Groq answer', async () => {
  resetTelemetryBufferForTests();
  resetActiveScenarios();
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
    resetActiveScenarios();
  }
});

void test('server scenario faults the real Groq path and preserves provenance', async () => {
  resetTelemetryBufferForTests();
  setActiveScenarios(['wrong_number']);
  const originalFetch = globalThis.fetch;
  const previousGroqKey = process.env.GROQ_API_KEY;
  const previousModelId = process.env.DRIFTZERO_MODEL_ID;
  process.env.GROQ_API_KEY = 'unit-test-key-that-must-not-leak';
  process.env.DRIFTZERO_MODEL_ID = 'shopassist-model';
  const groqPrompts: string[] = [];
  let monitoringPayload: Record<string, unknown> | undefined;
  globalThis.fetch = async (input, init) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    if (url.includes('api.groq.com')) {
      const body = init?.body;
      if (typeof body !== 'string')
        throw new Error('Expected a JSON Groq request body');
      const request = JSON.parse(body) as {
        messages: Array<{ content: string }>;
      };
      const prompt = request.messages[0]?.content ?? '';
      groqPrompts.push(prompt);
      const faulted = prompt.includes('ACTIVE DEMO STATE: wrong_number');
      return Response.json({
        id: `groq-request-${groqPrompts.length}`,
        model: 'openai/gpt-oss-120b',
        choices: [
          {
            finish_reason: 'stop',
            message: {
              content: JSON.stringify({
                answer: faulted
                  ? 'The Nimbus Adapter costs $129.'
                  : 'The Nimbus Adapter costs $119.',
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
      throw new Error('Expected a JSON monitoring request body');
    monitoringPayload = JSON.parse(body) as Record<string, unknown>;
    return Response.json({}, { status: 201 });
  };

  try {
    let faultedPayload: Record<string, unknown> | undefined;
    for (let index = 0; index < 20; index += 1) {
      const response = await POST(
        new Request('http://shopassist.test/api/chat', {
          method: 'POST',
          body: JSON.stringify({
            message: 'What is the price of the Nimbus Adapter?',
            history: [],
            scenarios: ['healthy'],
          }),
        }),
      );
      faultedPayload = (await response.json()) as Record<string, unknown>;
    }

    assert.equal(faultedPayload?.answer, 'The Nimbus Adapter costs $129.');
    assert.equal(faultedPayload?.model, 'openai/gpt-oss-120b');
    assert.equal(faultedPayload?.interactionId, 'groq-request-20');
    assert.deepEqual(faultedPayload?.scenarios, ['wrong_number']);
    assert.equal(faultedPayload?.telemetry, 'sent');
    assert.doesNotMatch(JSON.stringify(faultedPayload), /unit-test-key/);
    assert.match(groqPrompts[0] ?? '', /deliberately altered value/);
    const interactions = monitoringPayload?.interactions as Array<
      Record<string, unknown>
    >;
    assert.equal(interactions[0]?.answer, 'The Nimbus Adapter costs $129.');
    assert.equal(interactions[0]?.provider, 'groq');
    assert.equal(interactions[0]?.model_name, 'openai/gpt-oss-120b');
    assert.equal(interactions[0]?.request_id, 'groq-request-1');
    assert.equal(interactions[0]?.input_tokens, 90);
    assert.equal(interactions[0]?.output_tokens, 18);
    assert.equal(interactions[0]?.is_simulated, true);

    resetActiveScenarios();
    const normalResponse = await POST(
      new Request('http://shopassist.test/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: 'What is the price of the Nimbus Adapter?',
          history: [],
          scenarios: ['wrong_number'],
        }),
      }),
    );
    const normalPayload = (await normalResponse.json()) as Record<string, unknown>;
    assert.equal(normalPayload.answer, 'The Nimbus Adapter costs $119.');
    assert.deepEqual(normalPayload.scenarios, ['healthy']);
    assert.doesNotMatch(groqPrompts.at(-1) ?? '', /deliberately altered value/);
  } finally {
    globalThis.fetch = originalFetch;
    if (previousGroqKey === undefined) delete process.env.GROQ_API_KEY;
    else process.env.GROQ_API_KEY = previousGroqKey;
    if (previousModelId === undefined) delete process.env.DRIFTZERO_MODEL_ID;
    else process.env.DRIFTZERO_MODEL_ID = previousModelId;
    resetTelemetryBufferForTests();
    resetActiveScenarios();
  }
});
