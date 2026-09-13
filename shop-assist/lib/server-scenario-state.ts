import {
  DEFAULT_SCENARIO,
  normalizeScenarios,
  type ScenarioId,
} from './demo-state.ts';

const STATE_KEY = '__shopassistActiveScenariosV1';

type ScenarioStateGlobal = typeof globalThis & {
  [STATE_KEY]?: ScenarioId[];
};

function state(): ScenarioStateGlobal {
  return globalThis as ScenarioStateGlobal;
}

export function getActiveScenarios(): ScenarioId[] {
  return [...(state()[STATE_KEY] ?? [DEFAULT_SCENARIO])];
}

export function setActiveScenarios(values: readonly ScenarioId[]): ScenarioId[] {
  const normalized = normalizeScenarios(values);
  state()[STATE_KEY] = normalized;
  return [...normalized];
}

export function resetActiveScenarios(): ScenarioId[] {
  return setActiveScenarios([DEFAULT_SCENARIO]);
}
