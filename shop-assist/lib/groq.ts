const GROQ_ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions';
export const GROQ_MODEL = 'openai/gpt-oss-120b';

type GroqMessage = {
  content?: string | null;
};

type GroqChoice = {
  finish_reason?: string;
  message?: GroqMessage;
};

type GroqCompletion = {
  id?: string;
  model?: string;
  choices?: GroqChoice[];
  usage?: {
    total_tokens?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    prompt_tokens_details?: { cached_tokens?: number };
    completion_tokens_details?: { reasoning_tokens?: number };
  };
};

export type GroqReply = {
  answer: string;
  interactionId?: string;
  model: string;
  status: string;
  usage?: {
    totalTokens?: number;
    inputTokens?: number;
    outputTokens?: number;
    cachedTokens?: number;
    reasoningTokens?: number;
  };
  rateLimit?: {
    remainingRequests?: number;
    remainingTokens?: number;
    resetRequests?: string;
    resetTokens?: string;
  };
};

function optionalNumber(value: string | null): number | undefined {
  if (value === null) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function extractGroqText(completion: GroqCompletion): string {
  return completion.choices?.[0]?.message?.content?.trim() ?? '';
}

export function createGroqRequest(prompt: string, responseSchema?: object): object {
  return {
    model: GROQ_MODEL,
    messages: [{ role: 'user', content: prompt }],
    temperature: 0.1,
    reasoning_effort: 'low',
    max_completion_tokens: 384,
    ...(responseSchema ? {
      response_format: {
        type: 'json_schema',
        json_schema: {
          name: 'shopassist_grounded_response',
          strict: true,
          schema: responseSchema,
        },
      },
    } : {}),
  };
}

export async function sendGroqMessage(prompt: string, apiKey: string, responseSchema?: object): Promise<GroqReply> {
  const response = await fetch(GROQ_ENDPOINT, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(createGroqRequest(prompt, responseSchema)),
    signal: AbortSignal.timeout(30_000),
  });

  if (!response.ok) {
    throw new Error(`Groq request failed with status ${response.status}`);
  }

  const completion = await response.json() as GroqCompletion;
  const answer = extractGroqText(completion);
  if (!answer) throw new Error('Groq returned no text answer');

  return {
    answer,
    interactionId: completion.id,
    model: completion.model ?? GROQ_MODEL,
    status: completion.choices?.[0]?.finish_reason ?? 'completed',
    usage: completion.usage ? {
      totalTokens: completion.usage.total_tokens,
      inputTokens: completion.usage.prompt_tokens,
      outputTokens: completion.usage.completion_tokens,
      cachedTokens: completion.usage.prompt_tokens_details?.cached_tokens,
      reasoningTokens: completion.usage.completion_tokens_details?.reasoning_tokens,
    } : undefined,
    rateLimit: {
      remainingRequests: optionalNumber(response.headers.get('x-ratelimit-remaining-requests')),
      remainingTokens: optionalNumber(response.headers.get('x-ratelimit-remaining-tokens')),
      resetRequests: response.headers.get('x-ratelimit-reset-requests') ?? undefined,
      resetTokens: response.headers.get('x-ratelimit-reset-tokens') ?? undefined,
    },
  };
}
