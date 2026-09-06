const GEMINI_ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/interactions';
export const GEMINI_MODEL = 'gemini-3.8-flash';

type GeminiContent = {
  type?: string;
  text?: string;
};

type GeminiStep = {
  type?: string;
  content?: GeminiContent[];
};

type GeminiInteraction = {
  id?: string;
  status?: string;
  model?: string;
  steps?: GeminiStep[];
  usage?: {
    total_tokens?: number;
    total_input_tokens?: number;
    total_output_tokens?: number;
  };
};

export type GeminiReply = {
  answer: string;
  interactionId?: string;
  model: string;
  status: string;
  usage?: {
    totalTokens?: number;
    inputTokens?: number;
    outputTokens?: number;
  };
};

export function extractGeminiText(interaction: GeminiInteraction): string {
  return interaction.steps
    ?.filter((step) => step.type === 'model_output')
    .flatMap((step) => step.content ?? [])
    .filter((content) => content.type === 'text' && content.text)
    .map((content) => content.text)
    .join('\n')
    .trim() ?? '';
}

export async function sendGeminiMessage(message: string, apiKey: string, responseSchema?: object): Promise<GeminiReply> {
  const response = await fetch(GEMINI_ENDPOINT, {
    method: 'POST',
    headers: {
      'Api-Revision': '2026-05-20',
      'Content-Type': 'application/json',
      'x-goog-api-key': apiKey,
    },
    body: JSON.stringify({
      model: GEMINI_MODEL,
      input: message,
      store: false,
      ...(responseSchema ? { response_format: { type: 'text', mime_type: 'application/json', schema: responseSchema } } : {}),
    }),
    signal: AbortSignal.timeout(30_000),
  });

  if (!response.ok) {
    throw new Error(`Gemini request failed with status ${response.status}`);
  }

  const interaction = await response.json() as GeminiInteraction;
  const answer = extractGeminiText(interaction);
  if (!answer) throw new Error('Gemini returned no text answer');

  return {
    answer,
    interactionId: interaction.id,
    model: interaction.model ?? GEMINI_MODEL,
    status: interaction.status ?? 'completed',
    usage: interaction.usage ? {
      totalTokens: interaction.usage.total_tokens,
      inputTokens: interaction.usage.total_input_tokens,
      outputTokens: interaction.usage.total_output_tokens,
    } : undefined,
  };
}
