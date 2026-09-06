import { sendGeminiMessage } from '../../../lib/gemini.ts';
import { buildGroundedPrompt, groundedResponseSchema, parseGroundedResponse, resolveGroundingSources, type ChatHistoryEntry } from '../../../lib/shop-assist-prompt.ts';

type ChatRequest = {
  message?: unknown;
  history?: unknown;
};

function readHistory(value: unknown): ChatHistoryEntry[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 10) return null;
  const history: ChatHistoryEntry[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== 'object') return null;
    const role = 'role' in entry ? entry.role : undefined;
    const text = 'text' in entry ? entry.text : undefined;
    if ((role !== 'user' && role !== 'assistant') || typeof text !== 'string' || !text.trim() || text.length > 2_000) return null;
    history.push({ role, text: text.trim() });
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
    return Response.json({ error: 'invalid_history', detail: 'History must contain at most 10 valid chat messages.' }, { status: 400 });
  }

  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    return Response.json({ error: 'gemini_not_configured', detail: 'The ShopAssist Gemini connection is not configured.' }, { status: 503 });
  }

  try {
    const prompt = buildGroundedPrompt(message, history);
    const reply = await sendGeminiMessage(prompt, apiKey, groundedResponseSchema);
    const grounded = parseGroundedResponse(reply.answer);
    return Response.json({ ...reply, answer: grounded.answer, sources: resolveGroundingSources(grounded.sourceIds) });
  } catch (error) {
    console.error('ShopAssist Gemini request failed', error instanceof Error ? error.message : 'Unknown error');
    return Response.json({ error: 'gemini_unavailable', detail: 'Gemini could not answer right now.' }, { status: 502 });
  }
}
