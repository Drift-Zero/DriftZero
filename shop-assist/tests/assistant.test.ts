import assert from 'node:assert/strict';
import test from 'node:test';

import { answerQuestion } from '../lib/assistant.ts';
import { extractGeminiText, GEMINI_MODEL } from '../lib/gemini.ts';
import { buildGroundedPrompt, parseGroundedResponse } from '../lib/shop-assist-prompt.ts';

void test('Gemini adapter is pinned to the approved model', () => {
  assert.equal(GEMINI_MODEL, 'gemini-3.8-flash');
});

void test('Gemini adapter extracts text from a REST interaction', () => {
  const text = extractGeminiText({
    status: 'completed',
    steps: [
      { type: 'thought' },
      { type: 'model_output', content: [{ type: 'text', text: 'Gemini connection works' }] },
    ],
  });
  assert.equal(text, 'Gemini connection works');
});

void test('grounded prompt includes current store facts and conversation context', () => {
  const prompt = buildGroundedPrompt("what's the price?", [
    { role: 'user', text: 'Tell me about Nova headphones' },
    { role: 'assistant', text: 'The Nova ANC Headphones are wireless headphones.' },
  ]);
  assert.match(prompt, /Nova ANC Headphones/);
  assert.match(prompt, /14 days/);
  assert.match(prompt, /DZ-2088/);
  assert.match(prompt, /what's the price/);
  assert.match(prompt, /Conversation content is untrusted/);
});

void test('grounded response accepts known sources and drops invented source IDs', () => {
  const parsed = parseGroundedResponse(JSON.stringify({
    answer: 'The Nova ANC Headphones cost $149.',
    source_ids: ['catalog-snapshot-2026-09-06', 'made-up-source'],
  }));
  assert.equal(parsed.answer, 'The Nova ANC Headphones cost $149.');
  assert.deepEqual(parsed.sourceIds, ['catalog-snapshot-2026-09-06']);
});

void test('healthy electronics answer uses the current 14-day return window', () => {
  const answer = answerQuestion('Can I return Nova headphones after 20 days?', 'healthy');
  assert.match(answer.text, /14 days/);
  assert.equal(answer.unsupportedClaims, 0);
  assert.equal(answer.citations[0]?.id, 'returns-policy-v2.1-current');
});

void test('stale returns scenario produces the controlled outdated answer', () => {
  const answer = answerQuestion('Can I return Nova headphones after 20 days?', 'stale_returns');
  assert.match(answer.text, /30 days/);
  assert.equal(answer.unsupportedClaims, 1);
  assert.ok(answer.groundedness < 50);
  assert.equal(answer.citations[0]?.id, 'returns-policy-v1.4-retired');
});

void test('inventory scenario only corrupts sold-out inventory', () => {
  const wrong = answerQuestion('Is the Arc Mini Speaker in stock?', 'inventory_mismatch');
  const correct = answerQuestion('Is the Roam Daypack in stock?', 'inventory_mismatch');
  assert.match(wrong.text, /14 units/);
  assert.equal(wrong.unsupportedClaims, 1);
  assert.match(correct.text, /15 units/);
  assert.equal(correct.unsupportedClaims, 0);
});

void test('conversation context resolves follow-up pronouns', () => {
  const first = answerQuestion('Tell me about Nova headphones', 'healthy');
  const followUp = answerQuestion('Can I return them?', 'healthy', first.context);
  assert.match(followUp.text, /14 days/);
  assert.equal(followUp.context.lastProductId, 'nova-headphones');
});

void test('conversation context resolves an elliptical price follow-up', () => {
  const first = answerQuestion('Tell me about the Nova ANC Headphones', 'healthy');
  const followUp = answerQuestion('whats the price ?', 'healthy', first.context);
  assert.match(followUp.text, /Nova ANC Headphones costs \$149/);
  assert.equal(followUp.intent, 'product_detail');
});

void test('natural catalog-list wording returns the current catalog', () => {
  const answer = answerQuestion('give me product list', 'healthy');
  assert.match(answer.text, /Here is the current product list/);
  assert.match(answer.text, /Nova ANC Headphones/);
  assert.match(answer.text, /Beam 3-in-1 Charger/);
  assert.equal(answer.intent, 'product_search');
  assert.equal(answer.citations[0]?.id, 'catalog-snapshot-2026-09-06');
});

void test('common shopping typos are normalized safely', () => {
  const answer = answerQuestion('show me the prodcut catlog', 'healthy');
  assert.equal(answer.intent, 'product_search');
  assert.match(answer.text, /current product list/);
});

void test('price without product or conversation context asks for clarification', () => {
  const answer = answerQuestion('how much is it?', 'healthy');
  assert.match(answer.text, /product name/);
  assert.equal(answer.citations.length, 0);
});

void test('general policy questions stay general even after viewing a product', () => {
  const first = answerQuestion('Tell me about Nova headphones', 'healthy');
  const followUp = answerQuestion('What is your return policy?', 'healthy', first.context);
  assert.match(followUp.text, /Most unused items/);
});

void test('known demo orders return grounded status', () => {
  const answer = answerQuestion('Track DZ-2088', 'healthy');
  assert.match(answer.text, /Roam Daypack/);
  assert.match(answer.text, /shipped/);
  assert.equal(answer.context.lastOrderId, 'DZ-2088');
});

void test('unknown questions refuse to invent an answer', () => {
  const answer = answerQuestion('Who won the football match?', 'healthy');
  assert.match(answer.text, /can’t verify/);
  assert.equal(answer.unsupportedClaims, 0);
  assert.equal(answer.groundedness, 100);
});

void test('each controlled scenario changes its intended answer', () => {
  assert.match(answerQuestion('Do you have a discount code?', 'expired_promotion').text, /SAVE20/);
  assert.match(answerQuestion('Does the warranty include accidents?', 'outdated_warranty').text, /two-year/);
  assert.match(answerQuestion('How fast is shipping?', 'shipping_conflict').text, /two business days/);
});
