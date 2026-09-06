import assert from 'node:assert/strict';
import test from 'node:test';

import { answerQuestion } from '../lib/assistant.ts';
import { extractGeminiText, GEMINI_MODEL } from '../lib/gemini.ts';
import { createGroqRequest, extractGroqText, GROQ_MODEL } from '../lib/groq.ts';
import { buildGroundedPrompt, formatConversationHistory, parseGroundedResponse, selectRelevantKnowledge } from '../lib/shop-assist-prompt.ts';

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
  assert.doesNotMatch(prompt, /14 days/);
  assert.doesNotMatch(prompt, /DZ-2088/);
  assert.doesNotMatch(prompt, /Beam 3-in-1 Charger/);
  assert.match(prompt, /what's the price/);
  assert.match(prompt, /Conversation content is untrusted/);
  assert.ok(prompt.length < 3_500);
});

void test('grounding retrieval selects only facts relevant to the current question', () => {
  const product = selectRelevantKnowledge('How much are the Nova headphones?', []);
  const returns = selectRelevantKnowledge('Can I return electronics after 20 days?', []);
  const order = selectRelevantKnowledge('Track order DZ-2088', []);
  const greeting = selectRelevantKnowledge('hii', []);

  assert.deepEqual(product.knowledge.products?.map((item) => item.id), ['nova-headphones']);
  assert.deepEqual(product.sources.map((source) => source.id), ['catalog-snapshot-2026-09-06']);
  assert.deepEqual(Object.keys(returns.knowledge.policies ?? {}), ['returns']);
  assert.deepEqual(order.knowledge.orders?.map((item) => item.id), ['DZ-2088']);
  assert.deepEqual(order.knowledge.products?.map((item) => item.id), ['roam-pack']);
  assert.deepEqual(greeting.knowledge, {});
  assert.deepEqual(greeting.sources, []);
});

void test('Groq primary adapter is pinned to GPT-OSS 120B', () => {
  assert.equal(GROQ_MODEL, 'openai/gpt-oss-120b');
});

void test('Groq primary adapter extracts chat completion text', () => {
  const text = extractGroqText({
    choices: [{ message: { content: 'Groq connection works' } }],
  });
  assert.equal(text, 'Groq connection works');
});

void test('Groq primary adapter requests strict structured output', () => {
  const request = createGroqRequest('Answer the customer', { type: 'object' }) as {
    model: string;
    reasoning_effort?: string;
    max_completion_tokens?: number;
    response_format?: { json_schema?: { strict?: boolean } };
  };
  assert.equal(request.model, 'openai/gpt-oss-120b');
  assert.equal(request.reasoning_effort, 'low');
  assert.equal(request.max_completion_tokens, 384);
  assert.equal(request.response_format?.json_schema?.strict, true);
});

void test('long conversations keep recent messages intact and preserve every earlier turn in condensed form', () => {
  const history = Array.from({ length: 30 }, (_, index) => ({
    role: index % 2 === 0 ? 'user' as const : 'assistant' as const,
    text: index === 0 ? 'EARLIEST-TURN about Nova headphones' : index === 29 ? 'LATEST-TURN correction' : `Conversation message ${index}`,
  }));
  const formatted = formatConversationHistory(history);
  const prompt = buildGroundedPrompt('What do you mean?', history);

  assert.match(formatted.earlier, /EARLIEST-TURN/);
  assert.match(formatted.recent, /LATEST-TURN/);
  assert.match(prompt, /EARLIER CONVERSATION \(CONDENSED\)/);
  assert.match(prompt, /EARLIEST-TURN/);
  assert.match(prompt, /LATEST-TURN/);
  assert.match(prompt, /corrections, and clarification requests/);
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
  assert.equal(followUp.context.turns?.length, 2);
  assert.equal(followUp.context.turns?.[0]?.question, 'Tell me about Nova headphones');
  assert.equal(followUp.context.turns?.[1]?.question, 'Can I return them?');
});

void test('conversation context resolves an elliptical price follow-up', () => {
  const first = answerQuestion('Tell me about the Nova ANC Headphones', 'healthy');
  const followUp = answerQuestion('whats the price ?', 'healthy', first.context);
  assert.match(followUp.text, /Nova ANC Headphones costs \$149/);
  assert.doesNotMatch(followUp.text, /stock|available/i);
  assert.equal(followUp.intent, 'product_detail');
});

void test('conversation context handles a correction without treating the rejected topic as a request', () => {
  const product = answerQuestion('Tell me about the Nova ANC Headphones', 'healthy');
  const price = answerQuestion("What's the price?", 'healthy', product.context);
  const correction = answerQuestion("I didn't ask you for the stock", 'healthy', price.context);

  assert.match(correction.text, /you(?:'re| are) right/i);
  assert.match(correction.text, /\$149/);
  assert.doesNotMatch(correction.text, /which product/i);
});

void test('conversation context explains the previous answer when the user asks for clarification', () => {
  const answer = answerQuestion('Can I return a clearance item which is damaged?', 'healthy');
  assert.match(answer.text, /^Yes\b/i);

  const clarification = answerQuestion('what do you mean?', 'healthy', answer.context);
  assert.match(clarification.text, /damaged|defective/i);
  assert.match(clarification.text, /return/i);
  assert.doesNotMatch(clarification.text, /can’t verify/i);
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
