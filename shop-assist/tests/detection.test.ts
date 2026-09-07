import assert from 'node:assert/strict';
import test from 'node:test';

import { answerQuestion } from '../lib/assistant.ts';
import {
  buildDetectionReport,
  getRelevantDetectorChecks,
} from '../lib/detection.ts';

void test('multi-select combines faults and relevant detector checks', () => {
  const scenarios = ['wrong_numerical_answer', 'entity_mix_up'] as const;
  const answer = answerQuestion('Tell me about Nova ANC Headphones', scenarios);
  const report = buildDetectionReport({
    question: 'Tell me about Nova ANC Headphones',
    answer: answer.text,
    citations: answer.citations.map((citation) => citation.id),
    scenarios,
  });

  assert.match(answer.text, /\$199/);
  assert.match(answer.text, /fitness and sleep tracking/);
  assert.deepEqual(getRelevantDetectorChecks(scenarios), [
    'Source Grounding',
    'Numerical Accuracy',
    'Entity Accuracy',
  ]);
  assert.equal(report.overall.status, 'FAIL');
  assert.equal(
    report.checks.find((check) => check.name === 'Numerical Accuracy')?.status,
    'FAIL',
  );
  assert.equal(
    report.checks.find((check) => check.name === 'Entity Accuracy')?.status,
    'FAIL',
  );
});

void test('a current answer remains supported after a simulated source change', () => {
  const question = 'How many AeroBuds are in stock?';
  const first = answerQuestion(question, 'live_data_change');
  const baselineReport = buildDetectionReport({
    question,
    answer: first.text,
    citations: first.citations.map((citation) => citation.id),
    scenarios: ['live_data_change'],
  });
  const answer = answerQuestion(question, 'live_data_change', first.context);
  const report = buildDetectionReport({
    question,
    answer: answer.text,
    citations: answer.citations.map((citation) => citation.id),
    scenarios: ['live_data_change'],
    history: [
      { role: 'user', text: question },
      { role: 'assistant', text: first.text },
    ],
  });

  assert.equal(baselineReport.overall.status, 'PASS');
  assert.match(answer.text, /48 units/);
  assert.equal(report.overall.status, 'PASS');
  assert.match(report.overall.title, /source changed/i);
  assert.equal(
    report.checks.find((check) => check.name === 'Temporal Freshness')?.status,
    'PASS',
  );
});

void test('wrong order status is not hidden by matching order numbers', () => {
  const question = 'Track DZ-2088';
  const answer = answerQuestion(question, 'wrong_record');
  const report = buildDetectionReport({
    question,
    answer: answer.text,
    citations: answer.citations.map((citation) => citation.id),
    scenarios: ['wrong_record'],
  });

  assert.equal(
    report.checks.find((check) => check.name === 'Temporal Freshness')?.status,
    'FAIL',
  );
  assert.equal(report.overall.status, 'FAIL');
  assert.equal(report.overall.title, 'WRONG RECORD');
});
