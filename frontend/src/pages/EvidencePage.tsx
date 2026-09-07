import { Check, Database, FileCheck2, FileText, FileUp, Search, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { api } from '../api/endpoints'
import type { ApiEvidenceHit, ApiEvidenceSource, ApiModel } from '../api/types'

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

export function EvidencePage() {
  const [models, setModels] = useState<ApiModel[]>([])
  const [modelId, setModelId] = useState('')
  const [sources, setSources] = useState<ApiEvidenceSource[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [useLlm, setUseLlm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<ApiEvidenceHit[]>([])

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
    void api.evidenceSources(modelId).then(records => {
      if (active) setSources(records)
    }).catch(err => {
      if (active) setError(err instanceof Error ? err.message : 'Evidence sources could not be loaded.')
    })
    return () => { active = false }
  }, [modelId])

  const selectedModel = useMemo(() => models.find(model => model.id === modelId), [models, modelId])

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
      setFile(null); setUseLlm(false)
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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The review decision could not be saved.')
    } finally { setBusy(false) }
  }

  async function searchEvidence(event: FormEvent) {
    event.preventDefault()
    if (!modelId || !query.trim()) return
    setBusy(true); setError(null)
    try { setHits(await api.searchEvidence(modelId, query.trim())) }
    catch (err) { setError(err instanceof Error ? err.message : 'Evidence search failed.') }
    finally { setBusy(false) }
  }

  return <div className="page evidence-page">
    <header className="page-header">
      <div><p className="eyebrow">Verification corpus</p><h1>Trusted Evidence</h1><p>Import exact source facts, review them, then make them available to evaluators.</p></div>
      <div className="header-meta"><Database size={14}/> {sources.filter(source => source.status === 'approved').length} approved sources</div>
    </header>

    {error && <div className="evidence-error"><X size={15}/><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Dismiss error"><X size={13}/></button></div>}

    <section className="evidence-workspace">
      <form className="panel evidence-upload" onSubmit={upload}>
        <div className="panel-heading"><div><p className="panel-label">01 / Import</p><h2>Add a trusted source</h2></div><FileUp size={18}/></div>
        <label className="evidence-field"><span>Monitored model</span><select value={modelId} onChange={event => { setSources([]); setHits([]); setModelId(event.target.value) }} disabled={busy || !models.length}>{models.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
        <label className="evidence-drop" htmlFor="evidence-file"><FileText size={24}/><strong>{file?.name ?? 'Choose a source file'}</strong><span>PDF, JSON, CSV, TXT or Markdown · maximum 5 MB</span><input id="evidence-file" type="file" accept={ACCEPTED} onChange={event => setFile(event.target.files?.[0] ?? null)}/></label>
        <label className="evidence-ai"><input type="checkbox" checked={useLlm} onChange={event => setUseLlm(event.target.checked)} disabled={!file || !/\.(pdf|txt|md)$/i.test(file.name)}/><span><Sparkles size={14}/><strong>Structure unstructured text with AI</strong><small>Only exact, source-backed facts pass validation. Configure Gemini or Groq on the server.</small></span></label>
        <button className="button primary" type="submit" disabled={!file || !modelId || busy}>{busy ? 'Processing…' : 'Extract source evidence'}</button>
      </form>

      <div className="panel evidence-process">
        <div className="panel-heading"><div><p className="panel-label">How trust is created</p><h2>Parser before model</h2></div><FileCheck2 size={18}/></div>
        <ol><li><span>1</span><div><strong>Exact extraction</strong><p>Software reads values and keeps the page, row or JSON path.</p></div></li><li><span>2</span><div><strong>Optional AI structure</strong><p>The LLM creates atomic facts, but cannot replace the source quote.</p></div></li><li><span>3</span><div><strong>Human approval</strong><p>Nothing enters verification search until a reviewer approves it.</p></div></li></ol>
      </div>
    </section>

    <section className="panel evidence-library">
      <div className="panel-heading"><div><p className="panel-label">02 / Review</p><h2>{selectedModel?.name ?? 'Model'} evidence library</h2></div><span className="quiet-badge">{sources.length} sources</span></div>
      {!sources.length ? <div className="evidence-empty"><Database size={24}/><strong>No sources imported</strong><p>Upload a file to create the first reviewable corpus.</p></div> : <div className="source-list">{sources.map(source => <article key={source.id} className="source-card">
        <div className="source-summary"><span className={`source-status ${source.status}`}>{source.status.replace('_', ' ')}</span><div><strong>{source.name}</strong><p>{source.filename} · {source.chunk_count} chunks · {source.extraction_method}</p></div><code>{source.corpus_version}</code>{source.status === 'awaiting_review' && <div className="source-actions"><button type="button" className="button primary" disabled={busy} onClick={() => void review(source, 'approved')}><Check size={13}/> Approve</button><button type="button" className="button" disabled={busy} onClick={() => void review(source, 'rejected')}><X size={13}/> Reject</button></div>}{source.status === 'approved' && <button type="button" className="button" disabled={busy} onClick={() => void review(source, 'retired')}>Retire</button>}</div>
        <details><summary>Inspect extracted evidence</summary><div className="chunk-list">{source.chunks.slice(0, 20).map(chunk => <div key={chunk.id}><span>{locatorLabel(chunk.locator)}</span><p>{chunk.text}</p><small>{chunk.validation_status === 'exact_match' ? 'AI-structured · exact quote validated' : 'Deterministically extracted'}</small></div>)}{source.chunks.length > 20 && <p className="muted-copy">Showing the first 20 of {source.chunks.length} chunks.</p>}</div></details>
      </article>)}</div>}
    </section>

    <section className="panel evidence-search">
      <div className="panel-heading"><div><p className="panel-label">03 / Verify integration</p><h2>Search approved evidence</h2></div><Search size={18}/></div>
      <form onSubmit={searchEvidence}><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Example: What is the AeroFit price?"/><button className="button" type="submit" disabled={!query.trim() || busy}>Search</button></form>
      {hits.length > 0 && <div className="search-hits">{hits.map(hit => <article key={hit.chunk_id}><div><span>{hit.filename} · {locatorLabel(hit.locator)}</span><strong>{Math.round(hit.relevance * 100)}% match</strong></div><p>{hit.evidence_quote}</p><code>{hit.corpus_version}</code></article>)}</div>}
    </section>
  </div>
}
