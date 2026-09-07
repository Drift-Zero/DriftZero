/** Provider-neutral connector for Node.js 18+ model backends. */
export class DriftZeroConnector {
  constructor({ apiUrl, modelId, ingestionKey, batchSize = 20, latencyTargetMs = 2000, costTargetUsdPerInteraction = null }) {
    if (batchSize < 1 || batchSize > 100) throw new Error('batchSize must be between 1 and 100')
    this.endpoint = `${apiUrl.replace(/\/$/, '')}/api/v1/models/${modelId}/interactions/evaluate`
    this.ingestionKey = ingestionKey
    this.batchSize = batchSize
    this.latencyTargetMs = latencyTargetMs
    this.costTargetUsdPerInteraction = costTargetUsdPerInteraction
    this.buffer = []
  }

  async observe(interaction) {
    this.buffer.push({
      occurred_at: new Date().toISOString(),
      status: 'ok',
      safety_flags: [],
      ...interaction,
    })
    return this.buffer.length >= this.batchSize ? this.flush() : null
  }

  async flush() {
    if (!this.buffer.length) return null
    const interactions = this.buffer.slice(0, this.batchSize)
    const headers = { 'Content-Type': 'application/json' }
    if (this.ingestionKey) headers['X-DriftZero-Ingest-Key'] = this.ingestionKey
    const response = await fetch(this.endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        event_id: `connector:${crypto.randomUUID()}`,
        interactions,
        latency_target_ms: this.latencyTargetMs,
        cost_target_usd_per_interaction: this.costTargetUsdPerInteraction,
        source: 'observed',
        actor: 'owner-connector',
      }),
    })
    if (!response.ok) throw new Error(`DriftZero rejected the window: ${response.status} ${await response.text()}`)
    const result = await response.json()
    this.buffer.splice(0, interactions.length)
    return result
  }
}

// Example: call this after your Gemini, Groq, OpenAI, Ollama, vLLM, or custom model returns.
// await connector.observe({ question, answer, provider: 'ollama', latency_ms: elapsedMs })
