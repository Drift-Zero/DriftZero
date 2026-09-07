import { sendGroqMessage } from '../../../lib/groq.ts';
import {
  answerQuestion,
  type ConversationContext,
} from '../../../lib/assistant.ts';
import { products } from '../../../data/catalog.ts';
import {
  DEFAULT_SCENARIO,
  isScenarioId,
  normalizeScenarios,
} from '../../../lib/demo-state.ts';
import { buildDetectionReport } from '../../../lib/detection.ts';
import {
  buildGroundedPrompt,
  groundedResponseSchema,
  MAX_HISTORY_ENTRIES,
  parseGroundedResponse,
  resolveGroundingSources,
  type ChatHistoryEntry,
} from '../../../lib/shop-assist-prompt.ts';
import { recordInteraction } from '../../../lib/telemetry.ts';

type ChatRequest = {
  message?: unknown;
  history?: unknown;
  scenario?: unknown;
  scenarios?: unknown;
};

function readHistory(value: unknown): ChatHistoryEntry[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > MAX_HISTORY_ENTRIES) return null;
  const history: ChatHistoryEntry[] = [];
  let totalCharacters = 0;
  for (const entry of value) {
    if (!entry || typeof entry !== 'object') return null;
    const role = 'role' in entry ? entry.role : undefined;
    const text = 'text' in entry ? entry.text : undefined;
    if (
      (role !== 'user' && role !== 'assistant') ||
      typeof text !== 'string' ||
      !text.trim() ||
      text.length > 2_000
    )
      return null;
    const trimmedText = text.trim();
    totalCharacters += trimmedText.length;
    if (totalCharacters > 120_000) return null;
    history.push({ role, text: trimmedText });
  }
  return history;
}

function fallbackContext(history: ChatHistoryEntry[]): ConversationContext {
  const turns: NonNullable<ConversationContext['turns']> = [];
  let pendingQuestion = '';
  let lastProductId: string | undefined;
  for (const entry of history) {
    if (entry.role === 'user') {
      pendingQuestion = entry.text;
      continue;
    }
    const combined = `${pendingQuestion} ${entry.text}`.toLowerCase();
    const product = products.find(
      (item) =>
        combined.includes(item.name.toLowerCase()) ||
        item.aliases.some((alias) => combined.includes(alias.toLowerCase())),
    );
    if (product) lastProductId = product.id;
    turns.push({
      question: pendingQuestion,
      answer: entry.text,
      intent: 'history',
      productId: product?.id ?? lastProductId,
    });
    pendingQuestion = '';
  }
  return { lastProductId, turns: turns.slice(-20) };
}

export async function POST(request: Request): Promise<Response> {
  let body: ChatRequest;
  try {
    body = (await request.json()) as ChatRequest;
  } catch {
    return Response.json(
      { error: 'invalid_json', detail: 'Send a JSON request body.' },
      { status: 400 },
    );
  }

  if (typeof body.message !== 'string' || !body.message.trim()) {
    return Response.json(
      {
        error: 'invalid_message',
        detail: 'Message must be a non-empty string.',
      },
      { status: 400 },
    );
  }

  const message = body.message.trim();
  if (message.length > 4_000) {
    return Response.json(
      {
        error: 'message_too_long',
        detail: 'Message must be 4,000 characters or fewer.',
      },
      { status: 400 },
    );
  }

  const history = readHistory(body.history);
  if (!history) {
    return Response.json(
      {
        error: 'invalid_history',
        detail: `History must contain at most ${MAX_HISTORY_ENTRIES} valid chat messages and 120,000 characters.`,
      },
      { status: 400 },
    );
  }

  const rawScenarios = body.scenarios ?? body.scenario ?? DEFAULT_SCENARIO;
  const scenarioValues = Array.isArray(rawScenarios)
    ? rawScenarios
    : [rawScenarios];
  if (
    !scenarioValues.length ||
    scenarioValues.some((scenario) => !isScenarioId(scenario))
  ) {
    return Response.json(
      {
        error: 'invalid_scenario',
        detail: 'One or more selected demo scenarios are not valid.',
      },
      { status: 400 },
    );
  }
  const scenarios = normalizeScenarios(scenarioValues);

  const apiKey = process.env.GROQ_API_KEY;
  const startedAt = Date.now();
  const reference = answerQuestion(
    message,
    scenarios,
    fallbackContext(history),
  );

  const record = (
    answer: string,
    citations: string[],
    inputTokens = 0,
    outputTokens = 0,
  ) =>
    recordInteraction({
      question: message,
      answer,
      scenarios,
      citations,
      intent: reference.intent,
      latencyMs: Date.now() - startedAt,
      inputTokens,
      outputTokens,
      status: 'ok',
    });
  const detect = (answer: string, citations: string[]) =>
    buildDetectionReport({
      question: message,
      answer,
      citations,
      scenarios,
      history,
    });

  if (!apiKey) {
    const telemetry = await record(
      reference.text,
      reference.citations.map((item) => item.id),
    );
    return Response.json({
      answer: reference.text,
      model: 'Local grounded fallback',
      status: 'completed',
      sources: reference.citations,
      telemetry,
      detection: detect(
        reference.text,
        reference.citations.map((item) => item.id),
      ),
    });
  }

  try {
    const prompt = buildGroundedPrompt(message, history, scenarios);
    const reply = await sendGroqMessage(prompt, apiKey, groundedResponseSchema);
    const grounded = parseGroundedResponse(reply.answer);
    const telemetry = await record(
      grounded.answer,
      grounded.sourceIds,
      reply.usage?.inputTokens,
      reply.usage?.outputTokens,
    );
    return Response.json({
      ...reply,
      answer: grounded.answer,
      sources: resolveGroundingSources(grounded.sourceIds),
      telemetry,
      detection: detect(grounded.answer, grounded.sourceIds),
    });
  } catch (error) {
    console.error(
      'ShopAssist Groq request failed',
      error instanceof Error ? error.message : 'Unknown error',
    );
    const telemetry = await record(
      reference.text,
      reference.citations.map((item) => item.id),
    );
    return Response.json({
      answer: reference.text,
      model: 'Local grounded fallback',
      status: 'completed',
      sources: reference.citations,
      telemetry,
      detection: detect(
        reference.text,
        reference.citations.map((item) => item.id),
      ),
      providerError: 'groq_unavailable',
    });
  }
}
