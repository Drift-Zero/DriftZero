import { sendGroqMessage } from '../../../lib/groq.ts';
import { answerQuestion } from '../../../lib/assistant.ts';
import { DEFAULT_SCENARIO, isScenarioId } from '../../../lib/demo-state.ts';
import { buildGroundedPrompt, groundedResponseSchema, MAX_HISTORY_ENTRIES, parseGroundedResponse, resolveGroundingSources, type ChatHistoryEntry } from '../../../lib/shop-assist-prompt.ts';
import { recordInteraction } from '../../../lib/telemetry.ts';

type ChatRequest = {
  message?: unknown;
  history?: unknown;
  scenario?: unknown;
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
    if ((role !== 'user' && role !== 'assistant') || typeof text !== 'string' || !text.trim() || text.length > 2_000) return null;
    const trimmedText = text.trim();
    totalCharacters += trimmedText.length;
    if (totalCharacters > 120_000) return null;
    history.push({ role, text: trimmedText });
  }
  return history;
}

export async function POST(request: Request): Promise<Response> {
  let body: ChatRequest;
  try {
    body = await request.json() as ChatRequest;
  } catch {
    return Response.json({ error: 'invalid_json', detail: 'Send a JSON request body.' }, { status: 400 });
  }

  if (typeof body.message !== 'string' || !body.message.trim()) {
    return Response.json({ error: 'invalid_message', detail: 'Message must be a non-empty string.' }, { status: 400 });
  }

  const message = body.message.trim();
  if (message.length > 4_000) {
    return Response.json({ error: 'message_too_long', detail: 'Message must be 4,000 characters or fewer.' }, { status: 400 });
  }

  const history = readHistory(body.history);
  if (!history) {
    return Response.json({ error: 'invalid_history', detail: `History must contain at most ${MAX_HISTORY_ENTRIES} valid chat messages and 120,000 characters.` }, { status: 400 });
  }

  const scenario = body.scenario === undefined ? DEFAULT_SCENARIO : body.scenario;
  if (!isScenarioId(scenario)) {
    return Response.json({ error: 'invalid_scenario', detail: 'The selected demo scenario is not valid.' }, { status: 400 });
  }

  const apiKey = process.env.GROQ_API_KEY;
  const startedAt = Date.now();
  const reference = answerQuestion(message, scenario);

  const record = (answer: string, citations: string[], inputTokens = 0, outputTokens = 0) => recordInteraction({
    question: message, answer, scenario, citations, intent: reference.intent,
    latencyMs: Date.now() - startedAt, inputTokens, outputTokens, status: 'ok',
  });

  if (!apiKey) {
    const telemetry = await record(reference.text, reference.citations.map((item) => item.id));
    return Response.json({ answer: reference.text, model: 'Local grounded fallback', status: 'completed', sources: reference.citations, telemetry });
  }

  try {
    const prompt = buildGroundedPrompt(message, history, scenario);
    const reply = await sendGroqMessage(prompt, apiKey, groundedResponseSchema);
    const grounded = parseGroundedResponse(reply.answer);
    const telemetry = await record(grounded.answer, grounded.sourceIds, reply.usage?.inputTokens, reply.usage?.outputTokens);
    return Response.json({ ...reply, answer: grounded.answer, sources: resolveGroundingSources(grounded.sourceIds), telemetry });
  } catch (error) {
    console.error('ShopAssist Groq request failed', error instanceof Error ? error.message : 'Unknown error');
    const telemetry = await record(reference.text, reference.citations.map((item) => item.id));
    return Response.json({ answer: reference.text, model: 'Local grounded fallback', status: 'completed', sources: reference.citations, telemetry, providerError: 'groq_unavailable' });
  }
}
