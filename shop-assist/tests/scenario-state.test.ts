import assert from 'node:assert/strict';
import test from 'node:test';

import { GET, PUT } from '../app/api/demo-scenarios/route.ts';
import {
  getActiveScenarios,
  resetActiveScenarios,
} from '../lib/server-scenario-state.ts';
import {
  buildGroundedPrompt,
  selectRelevantKnowledge,
} from '../lib/shop-assist-prompt.ts';

void test('scenario control API owns active state and reset clears faults', async () => {
  resetActiveScenarios();
  const initial = await GET();
  assert.deepEqual((await initial.json()).scenarios, ['healthy']);

  const updated = await PUT(
    new Request('http://shopassist.test/api/demo-scenarios', {
      method: 'PUT',
      body: JSON.stringify({ scenarios: ['wrong_number'] }),
    }),
  );
  assert.equal(updated.status, 200);
  assert.deepEqual(getActiveScenarios(), ['wrong_number']);

  await PUT(
    new Request('http://shopassist.test/api/demo-scenarios', {
      method: 'PUT',
      body: JSON.stringify({ scenarios: ['healthy'] }),
    }),
  );
  assert.deepEqual(getActiveScenarios(), ['healthy']);
});

void test('controlled prompts are explicit and healthy prompt remains clean', () => {
  const healthy = buildGroundedPrompt('What does the Nimbus Adapter cost?', [], 'healthy');
  const wrongNumber = buildGroundedPrompt(
    'What does the Nimbus Adapter cost?',
    [],
    'wrong_number',
  );
  const policyMismatch = buildGroundedPrompt(
    'Can I return electronics after 20 days?',
    [],
    'policy_mismatch',
  );

  assert.match(healthy, /ACTIVE DEMO STATE: healthy/);
  assert.doesNotMatch(healthy, /controlled fault/);
  assert.match(wrongNumber, /deliberately altered value/);
  assert.match(wrongNumber, /Keep the requested product or entity correct/);
  assert.match(policyMismatch, /deliberately outdated policy/);
});

void test('wrong-number knowledge is derived for whichever product is requested', () => {
  const aero = selectRelevantKnowledge(
    'What is the price of AeroBuds?',
    [],
    'wrong_number',
  );
  const pulse = selectRelevantKnowledge(
    'What is the price of the Pulse Smartwatch?',
    [],
    'wrong_number',
  );

  assert.notEqual(aero.knowledge.products?.[0]?.price, 119);
  assert.notEqual(pulse.knowledge.products?.[0]?.price, 229);
  assert.notEqual(
    aero.knowledge.products?.[0]?.price,
    pulse.knowledge.products?.[0]?.price,
  );
});
