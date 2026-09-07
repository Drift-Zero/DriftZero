import { Activity, Check, CheckCircle2, Circle, Clock3, Database, FileText, FileUp, Globe2, Loader2, Play, RefreshCw, Search, ShieldCheck, Sparkles, X, XCircle } from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { api } from '../api/endpoints'
import type { ApiAutomatedEvaluation, ApiEvidenceHit, ApiEvidenceSource, ApiModel, ApiModelConnection, ApiWebsiteRefresh } from '../api/types'

const MAX_FILE_BYTES = 5 * 1024 * 1024
const ACCEPTED = '.pdf,.json,.csv,.txt,.md'

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('The file could not be read.'))
    reader.onload = () => {
      const result = String(reader.result ?? '')
      const comma = result.indexOf(',')
      if (comma < 0) reject(new Error('The file could not be encoded.'))
      else resolve(result.slice(comma + 1))
    }
    reader.readAsDataURL(file)
  })
}

function locatorLabel(locator: Record<string, unknown>): string {
  if (locator.page) return `Page ${locator.page}`
  if (locator.row) return `Row ${locator.row}`
  if (locator.json_path) return String(locator.json_path)
  if (locator.paragraph) return `Paragraph ${locator.paragraph}`
  return 'Source excerpt'
}

function friendlyField(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
}

export function EvidencePage() {
  const [models, setModels] = useState<ApiModel[]>([])
  const [modelId, setModelId] = useState('')
  const [connections, setConnections] = useState<ApiModelConnection[]>([])
  const [sources, setSources] = useState<ApiEvidenceSource[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [useLlm, setUseLlm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<ApiEvidenceHit[]>([])
  const [evaluation, setEvaluation] = useState<ApiAutomatedEvaluation | null>(null)
  const [questionCount, setQuestionCount] = useState(20)
  const [endpoint, setEndpoint] = useState('')
  const [requestField, setRequestField] = useState('message')
  const [responsePath, setResponsePath] = useState('answer')
  const [apiKey, setApiKey] = useState('')
  const [websiteUrl, setWebsiteUrl] = useState('')
  const [websiteName, setWebsiteName] = useState('')
  const [websiteInterval, setWebsiteInterval] = useState(10)
  const [websiteUseXai, setWebsiteUseXai] = useState(true)
  const [websiteAutoApprove, setWebsiteAutoApprove] = useState(false)
  const [websiteResult, setWebsiteResult] = useState<ApiWebsiteRefresh | null>(null)

  useEffect(() => {
    let active = true
    void api.models().then(records => {
      if (!active) return
      setModels(records)
      setModelId(current => current || records[0]?.id || '')
    }).catch(err => {
      if (active) setError(err instanceof Error ? err.message : 'The model registry is unavailable.')
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!modelId) return
    let active = true
    void Promise.all([api.evidenceSources(modelId), api.modelConnections(modelId)]).then(([sourceRecords, connectionRecords]) => {
      if (!active) return
      setSources(sourceRecords)
      setConnections(connectionRecords)
    }).catch(err => {
      if (active) setError(err instanceof Error ? err.message : 'Model setup could not be loaded.')
    })
    return () => { active = false }
  }, [modelId])

  const selectedModel = useMemo(() => models.find(model => model.id === modelId), [models, modelId])
  const approvedJson = useMemo(() => sources.filter(source => source.status === 'approved' && source.filename.toLowerCase().endsWith('.json')), [sources])
  const hasCallableModel = selectedModel?.provider.toLowerCase() === 'groq' || connections.some(connection => connection.kind === 'api' && ['configured', 'connected'].includes(connection.status))
  const websiteConnections = useMemo(() => connections.filter(connection => connection.kind === 'website'), [connections])

  async function upload(event: FormEvent) {
    event.preventDefault()
    if (!file || !modelId) return
    if (file.size > MAX_FILE_BYTES) { setError('Files must be 5 MB or smaller.'); return }
    setBusy(true); setError(null)
    try {
      const imported = await api.importEvidence(modelId, {
        filename: file.name,
        media_type: file.type || undefined,
        content_base64: await fileToBase64(file),
        use_llm: useLlm,
        actor: 'evidence-owner',
      })
      setSources(current => [imported, ...current])
      setFile(null); setUseLlm(false); setEvaluation(null)
      const input = document.getElementById('evidence-file') as HTMLInputElement | null
      if (input) input.value = ''
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The source could not be imported.')
    } finally { setBusy(false) }
  }

  async function review(source: ApiEvidenceSource, status: 'approved' | 'rejected' | 'retired') {
    const reason = status === 'rejected' ? 'Rejected during source review.' : undefined
    setBusy(true); setError(null)
    try {
      const updated = await api.reviewEvidence(source.id, status, reason)
      setSources(current => current.map(item => item.id === updated.id ? updated : item))
      setEvaluation(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The review decision could not be saved.')
    } finally { setBusy(false) }
  }

  async function runEvaluation() {
    if (!modelId) return
    setBusy(true); setError(null); setEvaluation(null)
    try {
      setEvaluation(await api.runAutomatedEvaluation(modelId, {
        max_questions: questionCount,
        variants_per_fact: 5,
        latency_best_ms: 200,
        latency_worst_ms: 2000,
      }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The automatic health check could not run.')
    } finally { setBusy(false) }
  }

  async function connectModel(event: FormEvent) {
    event.preventDefault()
    if (!modelId || !endpoint.trim()) return
    setBusy(true); setError(null)
    try {
      const connection = await api.createModelConnection(modelId, {
        name: 'Automatic evaluation endpoint',
        api_endpoint: endpoint.trim(),
        auth_scheme: apiKey ? 'bearer' : undefined,
        api_key: apiKey || undefined,
        config: {
          request_field: requestField.trim() || 'message',
          response_path: responsePath.trim() || 'answer',
          sample_request: { [requestField.trim() || 'message']: 'DriftZero connection test' },
        },
      })
      const checked = await api.checkModelConnection(connection.id)
      setConnections(current => [...current, checked.connection])
      setApiKey('')
      if (!checked.healthy) setError(checked.connection.last_error ?? 'The endpoint was saved but did not pass its connection check.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The model endpoint could not be connected.')
    } finally { setBusy(false) }
  }

  async function connectWebsite(event: FormEvent) {
    event.preventDefault()
    if (!modelId || !websiteUrl.trim()) return
    setBusy(true); setError(null); setWebsiteResult(null)
    try {
      const connection = await api.createWebsiteConnection(modelId, {
        name: websiteName.trim() || new URL(websiteUrl).hostname,
        url: websiteUrl.trim(),
        config: {
          refresh_interval_minutes: websiteInterval,
          use_xai: websiteUseXai,
          auto_approve: websiteAutoApprove,
        },
      })
      setConnections(current => [...current, connection])
      const result = await api.refreshWebsite(connection.id)
      setWebsiteResult(result)
      const [sourceRecords, connectionRecords] = await Promise.all([
        api.evidenceSources(modelId),
        api.modelConnections(modelId),
      ])
      setSources(sourceRecords); setConnections(connectionRecords); setWebsiteUrl(''); setWebsiteName('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The website monitor could not be created.')
    } finally { setBusy(false) }
  }

  async function refreshWebsite(connection: ApiModelConnection) {
    setBusy(true); setError(null); setWebsiteResult(null)
    try {
      setWebsiteResult(await api.refreshWebsite(connection.id))
      const [sourceRecords, connectionRecords] = await Promise.all([
        api.evidenceSources(modelId),
        api.modelConnections(modelId),
      ])
      setSources(sourceRecords); setConnections(connectionRecords)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The website could not be refreshed.')
    } finally { setBusy(false) }
  }

  async function searchEvidence(event: FormEvent) {
    event.preventDefault()
    if (!modelId || !query.trim()) return
    setBusy(true); setError(null)
    try { setHits(await api.searchEvidence(modelId, query.trim())) }
    catch (err) { setError(err instanceof Error ? err.message : 'Reference search failed.') }
    finally { setBusy(false) }
  }

  const failedCases = evaluation?.cases.filter(item => !item.passed) ?? []
  const scoreTone = evaluation?.health_state === 'healthy' ? 'healthy' : evaluation?.health_state === 'warning' ? 'warning' : 'critical'

  return <div className="page evidence-page">
    <header className="page-header">
      <div><p className="eyebrow">Ground truth and automatic testing</p><h1>Reference Data</h1><p>Tell DriftZero what is correct, then let it test your model and explain every failure.</p></div>
      <div className="header-meta"><Database size={14}/> {approvedJson.length} approved JSON source{approvedJson.length === 1 ? '' : 's'}</div>
    </header>

    {error && <div className="evidence-error"><X size={15}/><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Dismiss error"><X size={13}/></button></div>}

    <section className="reference-journey" aria-label="Health check setup progress">
      <div className={sources.length ? 'complete' : 'current'}><span>{sources.length ? <CheckCircle2/> : <Circle/>}</span><div><small>Step 1</small><strong>Add correct information</strong><p>Upload the JSON your model should agree with.</p></div></div>
      <div className={approvedJson.length ? 'complete' : sources.length ? 'current' : ''}><span>{approvedJson.length ? <CheckCircle2/> : <Circle/>}</span><div><small>Step 2</small><strong>Confirm the source</strong><p>Approve it before DriftZero treats it as truth.</p></div></div>
      <div className={evaluation ? 'complete' : approvedJson.length ? 'current' : ''}><span>{evaluation ? <CheckCircle2/> : <Circle/>}</span><div><small>Step 3</small><strong>Run automatic questions</strong><p>See the score and exactly what failed.</p></div></div>
    </section>

    <section className="evidence-workspace">
      <form className="panel evidence-upload" onSubmit={upload}>
        <div className="panel-heading"><div><p className="panel-label">01 / Add ground truth</p><h2>What should the model know?</h2></div><FileUp size={18}/></div>
        <label className="evidence-field"><span>Model to test</span><select value={modelId} onChange={event => { setSources([]); setHits([]); setConnections([]); setEvaluation(null); setModelId(event.target.value) }} disabled={busy || !models.length}>{models.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
        <label className="evidence-drop" htmlFor="evidence-file"><FileText size={24}/><strong>{file?.name ?? 'Choose your reference file'}</strong><span>JSON is best for automatic questions · maximum 5 MB</span><input id="evidence-file" type="file" accept={ACCEPTED} onChange={event => setFile(event.target.files?.[0] ?? null)}/></label>
        <label className="evidence-ai"><input type="checkbox" checked={useLlm} onChange={event => setUseLlm(event.target.checked)} disabled={!file || !/\.(pdf|txt|md)$/i.test(file.name)}/><span><Sparkles size={14}/><strong>Organize unstructured text with AI</strong><small>Optional for PDF, TXT and Markdown. JSON is always read directly.</small></span></label>
        <button className="button primary" type="submit" disabled={!file || !modelId || busy}>{busy ? <><Loader2 size={13} className="spin"/> Processing</> : 'Upload and inspect'}</button>
      </form>

      <div className="panel evidence-process">
        <div className="panel-heading"><div><p className="panel-label">What happens next</p><h2>No manual questions required</h2></div><ShieldCheck size={18}/></div>
        <ol><li><span>1</span><div><strong>Find testable facts</strong><p>Price, policy, availability and other values become expected answers.</p></div></li><li><span>2</span><div><strong>Ask several ways</strong><p>DriftZero creates paraphrases and sends them to the connected model.</p></div></li><li><span>3</span><div><strong>Calculate locally</strong><p>Answers are compared with your file; no evaluator invents the score.</p></div></li></ol>
      </div>
    </section>

    <section className="panel website-monitor">
      <div className="panel-heading"><div><p className="panel-label">Live source / Website to JSON</p><h2>Keep reference data current</h2><p>DriftZero fetches the page, asks Grok for strict JSON, validates every extracted value against an exact quote, and checks again on schedule.</p></div><Globe2 size={18}/></div>
      <form className="website-monitor-form" onSubmit={connectWebsite}>
        <label><span>Website URL</span><input type="url" value={websiteUrl} onChange={event => setWebsiteUrl(event.target.value)} placeholder="https://example.com/policies" required/></label>
        <label><span>Source name <em>optional</em></span><input value={websiteName} onChange={event => setWebsiteName(event.target.value)} placeholder="Current returns policy"/></label>
        <label><span>Refresh every</span><select value={websiteInterval} onChange={event => setWebsiteInterval(Number(event.target.value))}><option value={10}>10 minutes</option><option value={30}>30 minutes</option><option value={60}>1 hour</option><option value={360}>6 hours</option><option value={1440}>24 hours</option></select></label>
        <label className="website-option"><input type="checkbox" checked={websiteUseXai} onChange={event => setWebsiteUseXai(event.target.checked)}/><span><strong>Structure with Grok</strong><small>Uses the server-side XAI_API_KEY. The key never reaches the browser.</small></span></label>
        <label className="website-option"><input type="checkbox" checked={websiteAutoApprove} onChange={event => setWebsiteAutoApprove(event.target.checked)}/><span><strong>Automatically approve changes</strong><small>Leave off when a person should review each website revision before it affects scoring.</small></span></label>
        <button className="button primary" type="submit" disabled={busy || !modelId || !websiteUrl.trim()}>{busy ? <><Loader2 size={13} className="spin"/> Fetching website…</> : <><Globe2 size={14}/> Add and fetch website</>}</button>
      </form>
      {websiteResult && <div className="website-sync-result"><CheckCircle2 size={16}/><div><strong>{websiteResult.message}</strong><p>{websiteResult.fact_count} verified facts · content {websiteResult.content_hash.slice(0, 10)}</p></div></div>}
      {websiteConnections.length > 0 && <div className="website-connections">{websiteConnections.map(connection => <article key={connection.id}>
        <div><span className={`source-status ${connection.status === 'error' ? 'rejected' : 'approved'}`}>{connection.status}</span><strong>{connection.name}</strong><p>{connection.url}</p></div>
        <div><span><Clock3 size={13}/> Every {String(connection.config.refresh_interval_minutes ?? 10)} min</span><small>{connection.last_error ?? (connection.discovered_metadata.last_synced_at ? `Last checked ${new Date(String(connection.discovered_metadata.last_synced_at)).toLocaleString()}` : 'Waiting for first refresh')}</small></div>
        <button type="button" className="button" disabled={busy} onClick={() => void refreshWebsite(connection)}><RefreshCw size={13}/> Refresh now</button>
      </article>)}</div>}
    </section>

    <section className="panel evidence-library">
      <div className="panel-heading"><div><p className="panel-label">02 / Confirm</p><h2>{selectedModel?.name ?? 'Model'} reference library</h2></div><span className="quiet-badge">{sources.length} source{sources.length === 1 ? '' : 's'}</span></div>
      {!sources.length ? <div className="evidence-empty"><Database size={24}/><strong>No reference data yet</strong><p>Upload a JSON file to begin an automatic health check.</p></div> : <div className="source-list">{sources.map(source => <article key={source.id} className="source-card">
        <div className="source-summary"><span className={`source-status ${source.status}`}>{source.status === 'awaiting_review' ? 'Needs confirmation' : source.status}</span><div><strong>{source.name}</strong><p>{source.filename} · {source.chunk_count} facts found</p></div><code>{source.corpus_version}</code>{source.status === 'awaiting_review' && <div className="source-actions"><button type="button" className="button primary" disabled={busy} onClick={() => void review(source, 'approved')}><Check size={13}/> Use as truth</button><button type="button" className="button" disabled={busy} onClick={() => void review(source, 'rejected')}><X size={13}/> Reject</button></div>}{source.status === 'approved' && <button type="button" className="button" disabled={busy} onClick={() => void review(source, 'retired')}>Retire</button>}</div>
        <details><summary>Review what DriftZero found</summary><div className="chunk-list">{source.chunks.slice(0, 20).map(chunk => <div key={chunk.id}><span>{locatorLabel(chunk.locator)}</span><p>{chunk.text}</p><small>Read directly from your file</small></div>)}{source.chunks.length > 20 && <p className="muted-copy">Showing the first 20 of {source.chunks.length} facts.</p>}</div></details>
      </article>)}</div>}
    </section>

    <section className="panel automatic-check">
      <div className="panel-heading"><div><p className="panel-label">03 / Automatic health check</p><h2>Let DriftZero question the model</h2></div><Activity size={18}/></div>
      <div className="automatic-check-intro">
        <div><strong>{approvedJson.length ? `${approvedJson.reduce((sum, source) => sum + source.chunk_count, 0)} approved fact groups ready` : 'Approve a JSON source to continue'}</strong><p>Questions, expected answers and scoring are generated from approved data. Your model only supplies its answers.</p></div>
        <div className={`model-readiness ${hasCallableModel ? 'ready' : ''}`}>{hasCallableModel ? <CheckCircle2 size={15}/> : <Circle size={15}/>} {hasCallableModel ? 'Model connection ready' : 'Model connection required'}</div>
      </div>
      <div className="automatic-check-actions">
        <label><span>Questions to run</span><select value={questionCount} onChange={event => setQuestionCount(Number(event.target.value))} disabled={busy}><option value={10}>10 · quick preview</option><option value={20}>20 · Health Score</option><option value={30}>30 · higher confidence</option><option value={50}>50 · full check</option></select></label>
        <button type="button" className="button primary run-health-check" disabled={!approvedJson.length || !hasCallableModel || busy} onClick={() => void runEvaluation()}>{busy ? <><Loader2 size={15} className="spin"/> Asking the model…</> : <><Play size={14}/> Run automatic health check</>}</button>
      </div>
      {!hasCallableModel && <form className="inline-model-connection" onSubmit={connectModel}>
        <div><strong>Connect the model once</strong><p>DriftZero sends each generated question to this endpoint. No provider API key is needed if your endpoint is already accessible.</p></div>
        <label><span>Model endpoint</span><input type="url" value={endpoint} onChange={event => setEndpoint(event.target.value)} placeholder="https://your-model.example.com/chat" required/></label>
        <div className="connection-shape"><label><span>Question field</span><input value={requestField} onChange={event => setRequestField(event.target.value)} placeholder="message"/></label><label><span>Answer path</span><input value={responsePath} onChange={event => setResponsePath(event.target.value)} placeholder="answer"/></label><label><span>API key <em>optional</em></span><input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} autoComplete="new-password" placeholder="Sent once and encrypted"/></label></div>
        <button type="submit" className="button" disabled={busy || !endpoint.trim()}>{busy ? <Loader2 size={13} className="spin"/> : <Activity size={13}/>} Connect and test endpoint</button>
      </form>}

      {evaluation && <div className={`automatic-result ${scoreTone}`}>
        <div className="automatic-score"><div><small>Model Health</small><strong>{evaluation.health_score ?? 'Pending'}{evaluation.health_score !== null && <em>/100</em>}</strong><span>{evaluation.health_state.replace('_', ' ')}</span></div><div><strong>{evaluation.passed_questions}/{evaluation.generated_questions}</strong><span>questions passed</span><small>{evaluation.connection}</small></div></div>
        <p className="automatic-message">{evaluation.message}</p>
        <div className="automatic-metrics">{Object.entries(evaluation.dimensions).filter(([, value]) => value !== null && value !== undefined).map(([name, value]) => <div key={name}><span>{friendlyField(name)}</span><strong>{Math.round(Number(value))}</strong></div>)}</div>
        <div className="failure-heading"><div><XCircle size={16}/><span><strong>{failedCases.length} failed questions</strong><small>Open any row to see the expected and actual answer.</small></span></div><span>{evaluation.pass_rate}% pass rate</span></div>
        {failedCases.length === 0 ? <div className="all-passed"><CheckCircle2 size={18}/> Every generated question matched the approved data.</div> : <div className="failure-list">{failedCases.map((item, index) => <details key={`${item.question}:${index}`} open={index === 0}><summary><span>{item.question}</span><strong>{friendlyField(item.field)}</strong></summary><div><section><small>Expected from {item.source_name}</small><p>{item.expected}</p><code>{locatorLabel(item.locator)}</code></section><section><small>Model answered</small><p>{item.actual}</p><code>{item.latency_ms} ms</code></section></div></details>)}</div>}
        <details className="passed-questions"><summary>View {evaluation.passed_questions} passed questions</summary><div>{evaluation.cases.filter(item => item.passed).map((item, index) => <p key={`${item.question}:${index}`}><CheckCircle2 size={13}/><span>{item.question}</span><strong>{item.actual}</strong></p>)}</div></details>
      </div>}
    </section>

    <section className="panel evidence-search">
      <div className="panel-heading"><div><p className="panel-label">Optional / Explore</p><h2>Search your approved reference data</h2></div><Search size={18}/></div>
      <form onSubmit={searchEvidence}><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Example: What is the AeroFit price?"/><button className="button" type="submit" disabled={!query.trim() || busy}>Search</button></form>
      {hits.length > 0 && <div className="search-hits">{hits.map(hit => <article key={hit.chunk_id}><div><span>{hit.filename} · {locatorLabel(hit.locator)}</span><strong>{Math.round(hit.relevance * 100)}% match</strong></div><p>{hit.evidence_quote}</p><code>{hit.corpus_version}</code></article>)}</div>}
    </section>
  </div>
}
