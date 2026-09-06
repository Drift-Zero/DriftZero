'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Activity, ArrowLeft, Check, CircleAlert, Database, RotateCcw, ShieldCheck, Sparkles } from 'lucide-react';

import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { readScenario, scenarios, writeScenario, type ScenarioId } from '../../lib/demo-state.ts';

type ModelContextDocument = Document & {
  modelContext?: {
    registerTool(tool: {
      name: string;
      title: string;
      description: string;
      inputSchema: object;
      annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
      execute(input: unknown): object | Promise<object>;
    }, options?: { signal?: AbortSignal }): void | Promise<void>;
  };
};

const metricProfiles: Record<ScenarioId, { health: number; groundedness: number; claims: number; label: string }> = {
  healthy: { health: 92, groundedness: 98, claims: 0, label: 'Healthy baseline' },
  stale_returns: { health: 61, groundedness: 42, claims: 3, label: 'Knowledge drift' },
  inventory_mismatch: { health: 68, groundedness: 58, claims: 2, label: 'Catalog lag' },
  expired_promotion: { health: 70, groundedness: 55, claims: 2, label: 'Expired knowledge' },
  outdated_warranty: { health: 59, groundedness: 36, claims: 4, label: 'Warranty drift' },
  shipping_conflict: { health: 66, groundedness: 52, claims: 2, label: 'Source conflict' },
  recovered: { health: 86, groundedness: 98, claims: 0, label: 'Recovery verified' },
};

export default function DemoConsole() {
  const [active, setActiveState] = useState<ScenarioId>('healthy');
  const [buffered, setBuffered] = useState(0);
  const metrics = metricProfiles[active];

  function setActive(value: ScenarioId) {
    writeScenario(value);
    setActiveState(value);
  }

  useEffect(() => {
    queueMicrotask(() => {
      setActiveState(readScenario());
      try {
        setBuffered((JSON.parse(sessionStorage.getItem('shopassist.telemetry.v1') ?? '[]') as object[]).length);
      } catch {
        setBuffered(0);
      }
    });
  }, []);

  useEffect(() => {
    const context = (document as ModelContextDocument).modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const registration = context.registerTool({
      name: 'set_shopassist_demo_scenario',
      title: 'Set ShopAssist demo scenario',
      description: 'Activate a controlled ShopAssist reliability scenario in the visible customer experience.',
      inputSchema: {
        type: 'object',
        properties: { scenario: { type: 'string', enum: ['healthy', 'stale_returns', 'inventory_mismatch', 'expired_promotion', 'outdated_warranty', 'shipping_conflict', 'recovered'] } },
        required: ['scenario'],
        additionalProperties: false,
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      execute(input) {
        const scenario = (input as { scenario?: unknown }).scenario;
        const valid = ['healthy', 'stale_returns', 'inventory_mismatch', 'expired_promotion', 'outdated_warranty', 'shipping_conflict', 'recovered'];
        if (typeof scenario !== 'string' || !valid.includes(scenario)) throw new Error('Invalid ShopAssist scenario.');
        setActive(scenario as ScenarioId);
        return { scenario, status: 'active' };
      },
    }, { signal: lifecycle.signal });
    void Promise.resolve(registration).catch(() => undefined);
    return () => lifecycle.abort();
  }, []);

  return (
    <main className="demo-shell">
      <header className="demo-topbar">
        <div className="demo-brand"><span><Sparkles size={18} /></span><div><strong>ShopAssist Lab</strong><small>DriftZero scenario console</small></div></div>
        <Link href="/"><ArrowLeft size={15} />Customer view</Link>
      </header>

      <section className="demo-layout">
        <div className="scenario-column">
          <div className="demo-heading"><div><p className="eyebrow">Controlled failure injection</p><h1>Choose a reliability scenario</h1><p>Each scenario changes only the relevant knowledge source. All behavior is deterministic and simulated.</p></div><Badge variant="outline">PRESENTER ONLY</Badge></div>
          <div className="scenario-grid">
            {scenarios.map((scenario) => {
              const selected = active === scenario.id;
              return (
                <article key={scenario.id} className={`scenario-card ${selected ? 'selected' : ''}`}>
                  <div className="scenario-title"><span>{selected ? <CircleAlert size={18} /> : <Database size={18} />}</span><div><strong>{scenario.name}</strong><small>{scenario.metric}</small></div></div>
                  <p>{scenario.description}</p>
                  <div className="impact-line"><span>Expected impact</span><strong>{scenario.impact}</strong></div>
                  <Button variant={selected ? 'default' : 'outline'} size="sm" onClick={() => setActive(scenario.id)}>{selected ? <><Check size={14} />Active</> : 'Activate scenario'}</Button>
                </article>
              );
            })}
          </div>
        </div>

        <aside className="run-panel">
          <div className={`health-orb ${active === 'healthy' || active === 'recovered' ? 'good' : 'bad'}`}><span>{metrics.health}</span><small>health</small></div>
          <Badge variant="outline">{metrics.label}</Badge>
          <h2>{active === 'healthy' ? 'ShopAssist is stable' : active === 'recovered' ? 'Recovery is holding' : 'Degradation detected'}</h2>
          <p className="run-summary">{active === 'healthy' ? 'Current sources are indexed and answers are grounded.' : active === 'recovered' ? 'Current sources and citation enforcement are restored.' : 'Open the customer view and ask a related question to generate evidence.'}</p>
          <div className="run-metrics">
            <div><span>Groundedness</span><strong>{metrics.groundedness}%</strong></div>
            <div><span>Unsupported claims</span><strong>{metrics.claims}</strong></div>
            <div><span>Buffered traces</span><strong>{buffered}</strong></div>
          </div>
          {active !== 'healthy' && active !== 'recovered' ? (
            <Button className="recovery-button" onClick={() => setActive('recovered')}><ShieldCheck size={16} />Apply recovery</Button>
          ) : (
            <Button variant="outline" onClick={() => setActive('healthy')}><RotateCcw size={16} />Reset baseline</Button>
          )}
          <Link className="open-customer" href="/">Open customer view <Activity size={15} /></Link>
          <ol className="demo-steps">
            <li><span>1</span>Activate a failure scenario.</li>
            <li><span>2</span>Ask a matching question in customer view.</li>
            <li><span>3</span>Inspect the trace in DriftZero.</li>
            <li><span>4</span>Apply recovery and ask again.</li>
          </ol>
        </aside>
      </section>
    </main>
  );
}
