'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  ArrowLeftRight,
  ArrowLeft,
  Calculator,
  Check,
  CircleAlert,
  CircleHelp,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Link000, Link005 } from '../../components/ui/skiper-ui/skiper40';
import {
  isScenarioId,
  readScenarios,
  scenarios,
  writeScenarios,
  type HallucinationTestId,
  type ScenarioId,
} from '../../lib/demo-state.ts';
import {
  clearDetectionReport,
  getRelevantDetectorChecks,
  readDetectionReport,
  type DetectionReport,
} from '../../lib/detection.ts';

type ModelContextDocument = Document & {
  modelContext?: {
    registerTool(
      tool: {
        name: string;
        title: string;
        description: string;
        inputSchema: object;
        annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
        execute(input: unknown): object | Promise<object>;
      },
      options?: { signal?: AbortSignal },
    ): void | Promise<void>;
  };
};

const combinations: Array<{ name: string; ids: HallucinationTestId[] }> = [
  {
    name: 'Dynamic Data',
    ids: ['live_data_change', 'wrong_number'],
  },
  {
    name: 'Unsupported Claims',
    ids: ['made_up_detail', 'policy_mismatch'],
  },
  {
    name: 'Data Accuracy',
    ids: ['wrong_number', 'wrong_record'],
  },
];

function ScenarioIcon({ id }: { id: HallucinationTestId }) {
  if (id === 'live_data_change') return <RefreshCw size={18} />;
  if (id === 'made_up_detail') return <CircleHelp size={18} />;
  if (id === 'wrong_number') return <Calculator size={18} />;
  if (id === 'wrong_record') return <ArrowLeftRight size={18} />;
  return <ShieldCheck size={18} />;
}

export default function DemoConsole() {
  const [activeIds, setActiveIds] = useState<ScenarioId[]>(['healthy']);
  const [selectedIds, setSelectedIds] = useState<HallucinationTestId[]>([]);
  const [detection, setDetection] = useState<DetectionReport | null>(null);
  const selectedScenarios = useMemo(
    () => scenarios.filter((scenario) => selectedIds.includes(scenario.id)),
    [selectedIds],
  );
  const activeScenarios = scenarios.filter((scenario) =>
    activeIds.includes(scenario.id),
  );
  const isNormal = activeIds.length === 1 && activeIds[0] === 'healthy';
  const isRecovered = activeIds.length === 1 && activeIds[0] === 'recovered';

  function setActive(values: ScenarioId[]) {
    writeScenarios(values);
    setActiveIds(values);
  }

  function toggleTest(id: HallucinationTestId) {
    clearDetectionReport();
    setDetection(null);
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  }

  function selectTests(ids: HallucinationTestId[]) {
    clearDetectionReport();
    setDetection(null);
    setSelectedIds(ids);
  }

  function runSelectedTests() {
    if (!selectedIds.length) return;
    clearDetectionReport();
    setDetection(null);
    setActive(selectedIds);
  }

  useEffect(() => {
    queueMicrotask(() => {
      const saved = readScenarios();
      setActiveIds(saved);
      setSelectedIds(
        saved.filter((id): id is HallucinationTestId =>
          scenarios.some((scenario) => scenario.id === id),
        ),
      );
      setDetection(readDetectionReport());
    });
    const updateDetection = (event: Event) => {
      const detail = (event as CustomEvent<DetectionReport | null>).detail;
      setDetection(detail ?? readDetectionReport());
    };
    window.addEventListener('shopassist:detection', updateDetection);
    return () =>
      window.removeEventListener('shopassist:detection', updateDetection);
  }, []);

  useEffect(() => {
    const context = (document as ModelContextDocument).modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const registration = context.registerTool(
      {
        name: 'set_shopassist_demo_scenarios',
        title: 'Set ShopAssist demo tests',
        description:
          'Select one or more controlled ShopAssist test situations for the visible customer experience.',
        inputSchema: {
          type: 'object',
          properties: {
            scenarios: {
              type: 'array',
              minItems: 1,
              uniqueItems: true,
              items: {
                type: 'string',
                enum: scenarios.map((scenario) => scenario.id),
              },
            },
          },
          required: ['scenarios'],
          additionalProperties: false,
        },
        annotations: { readOnlyHint: false, untrustedContentHint: false },
        execute(input) {
          const values = (input as { scenarios?: unknown }).scenarios;
          if (
            !Array.isArray(values) ||
            !values.length ||
            values.some((value) => !isScenarioId(value))
          )
            throw new Error('Invalid ShopAssist test selection.');
          const ids = values as ScenarioId[];
          clearDetectionReport();
          setDetection(null);
          setActive(ids);
          setSelectedIds(ids as HallucinationTestId[]);
          return { scenarios: ids, status: 'active' };
        },
      },
      { signal: lifecycle.signal },
    );
    void Promise.resolve(registration).catch(() => undefined);
    return () => lifecycle.abort();
  }, []);

  return (
    <main className="demo-shell">
      <header className="demo-topbar">
        <div className="demo-brand">
          <span>
            <Sparkles size={18} />
          </span>
          <div>
            <strong>ShopAssist Lab</strong>
            <small>DriftZero scenario console</small>
          </div>
        </div>
        <Link000 href="/">
          <ArrowLeft size={15} />
          Customer view
        </Link000>
      </header>

      <section className="demo-layout">
        <div className="scenario-column">
          <div className="demo-heading">
            <div>
              <p className="eyebrow">Controlled AI failure demo</p>
              <h1>Choose Hallucination Tests</h1>
              <p>
                Select one or more real-world situations to see how DriftZero
                evaluates unreliable AI behavior.
              </p>
            </div>
            <Badge variant="outline">PRESENTER ONLY</Badge>
          </div>

          <div className="selection-toolbar">
            <div className="selection-summary">
              <strong>
                {selectedIds.length}{' '}
                {selectedIds.length === 1 ? 'test' : 'tests'} selected
              </strong>
              <span>
                Manual selection is for demo/testing. In production, DriftZero
                automatically runs all relevant checks.
              </span>
              {selectedIds.length > 3 && (
                <small>
                  For the clearest demo, we recommend combining up to 3 tests.
                </small>
              )}
            </div>
            <Button disabled={!selectedIds.length} onClick={runSelectedTests}>
              <Activity size={16} />
              Run Selected Tests
            </Button>
          </div>

          <div className="recommended-combinations">
            <span>Recommended combinations</span>
            <div>
              {combinations.map((combination) => (
                <button
                  key={combination.name}
                  type="button"
                  onClick={() => selectTests(combination.ids)}
                >
                  {combination.name}
                </button>
              ))}
            </div>
          </div>

          <div className="scenario-grid">
            {scenarios.map((scenario) => {
              const selected = selectedIds.includes(scenario.id);
              const running = activeIds.includes(scenario.id);
              return (
                <article
                  key={scenario.id}
                  className={`scenario-card ${selected ? 'selected' : ''}`}
                >
                  <div className="scenario-title">
                    <span>
                      {selected ? (
                        <Check size={18} />
                      ) : (
                        <ScenarioIcon id={scenario.id} />
                      )}
                    </span>
                    <div>
                      <strong>{scenario.name}</strong>
                      <Badge variant="outline">{scenario.category}</Badge>
                    </div>
                  </div>
                  <p className="scenario-situation">{scenario.situation}</p>
                  <div className="card-impact">
                    <span>Impact</span>
                    <Badge
                      className={`impact-badge ${scenario.impact.level.toLowerCase()}`}
                    >
                      {scenario.impact.level}
                    </Badge>
                  </div>
                  <Button
                    variant={selected ? 'default' : 'outline'}
                    size="sm"
                    aria-pressed={selected}
                    onClick={() => toggleTest(scenario.id)}
                  >
                    {selected ? (
                      <>
                        <Check size={14} />
                        {running ? 'Active · remove' : 'Selected · remove'}
                      </>
                    ) : (
                      'Add test'
                    )}
                  </Button>
                </article>
              );
            })}
          </div>
        </div>

        <aside className="run-panel">
          <div
            className={`agent-state-summary ${isNormal || isRecovered ? 'normal' : 'injected'}`}
          >
            <span>
              {isNormal || isRecovered ? (
                <ShieldCheck size={20} />
              ) : (
                <CircleAlert size={20} />
              )}
            </span>
            <div>
              <small>Current agent state</small>
              <strong>
                {isNormal
                  ? 'Running normally'
                  : isRecovered
                    ? 'Recovered'
                    : `${activeScenarios.length} test${activeScenarios.length === 1 ? '' : 's'} active`}
              </strong>
            </div>
          </div>

          {!isNormal && !isRecovered && (
            <section className="active-tests">
              <p className="eyebrow">Active tests</p>
              {activeScenarios.map((scenario) => (
                <span key={scenario.id}>
                  <Check size={13} />
                  {scenario.shortName}
                </span>
              ))}
            </section>
          )}

          {selectedScenarios.length ? (
            <div className="demo-plan">
              <div className="demo-plan-heading">
                <p className="eyebrow">Selected scenarios</p>
                <Badge variant="outline">
                  {selectedScenarios.length} selected
                </Badge>
              </div>
              {selectedScenarios.map((scenario) => (
                <section className="selected-scenario-plan" key={scenario.id}>
                  <h2>{scenario.name}</h2>
                  <div className="plan-copy">
                    <strong>What this test simulates</strong>
                    <span>{scenario.whatHappens}</span>
                  </div>
                  <div className="plan-copy">
                    <strong>What this demo will do</strong>
                    <ol className="demo-steps">
                      {scenario.steps.map((step, index) => (
                        <li key={step}>
                          <span>{index + 1}</span>
                          {step}
                        </li>
                      ))}
                    </ol>
                  </div>
                  <div className="detector-check-list">
                    <strong>What DriftZero checks</strong>
                    {getRelevantDetectorChecks([scenario.id]).map((check) => (
                      <span key={check}>
                        <Check size={12} />
                        {check}
                      </span>
                    ))}
                  </div>
                  <div className="expected-results">
                    <strong>Expected result</strong>
                    {scenario.passResult && (
                      <span className="expected-pass">
                        ✓ {scenario.passResult}
                      </span>
                    )}
                    <span className="expected-fail">
                      ✕ {scenario.failResult}
                    </span>
                  </div>
                </section>
              ))}
              <div className="scenario-check-distinction">
                <strong>Scenario ≠ detector check</strong>
                <span>
                  You choose the situations. DriftZero automatically applies the
                  reliability checks that fit the interaction.
                </span>
              </div>
            </div>
          ) : (
            <div className="demo-plan-empty">
              <CircleAlert size={22} />
              <h2>Select one or more tests</h2>
              <p>
                Choose cards or use a recommended combination to preview one
                combined demo flow.
              </p>
            </div>
          )}

          <section className="detection-results">
            <p className="eyebrow">Detection results</p>
            {detection ? (
              <>
                <div className="result-comparison">
                  <div>
                    <small>Trusted source</small>
                    <span>{detection.overall.trustedSource}</span>
                  </div>
                  <div>
                    <small>AI response</small>
                    <span>“{detection.overall.aiClaim}”</span>
                  </div>
                  <div
                    className={`result-verdict ${detection.overall.status.toLowerCase()}`}
                  >
                    <small>DriftZero</small>
                    <strong>
                      {detection.overall.status === 'PASS'
                        ? '✓'
                        : detection.overall.status === 'WARNING'
                          ? '!'
                          : '✕'}{' '}
                      {detection.overall.title}
                    </strong>
                  </div>
                </div>
                <div className="result-list">
                  {detection.checks.map((check) => (
                    <div key={check.id}>
                      <span>{check.name}</span>
                      <Badge
                        className={`result-badge ${check.status.toLowerCase()}`}
                      >
                        {check.status}
                      </Badge>
                      <small>{check.detail}</small>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="results-placeholder">
                Run the selected tests, then ask a question in Customer View.
                Results will appear here automatically.
              </p>
            )}
          </section>

          {!isNormal && !isRecovered && (
            <Button
              className="recovery-button"
              onClick={() => setActive(['recovered'])}
            >
              <ShieldCheck size={16} />
              Apply recovery
            </Button>
          )}
          {isRecovered && (
            <Button variant="outline" onClick={() => setActive(['healthy'])}>
              <RotateCcw size={16} />
              Reset baseline
            </Button>
          )}
          <Link005 className="open-customer" href="/">
            Open customer view <Activity size={15} />
          </Link005>
        </aside>
      </section>
    </main>
  );
}
