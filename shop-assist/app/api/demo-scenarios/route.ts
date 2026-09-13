import { isScenarioId } from '../../../lib/demo-state.ts';
import {
  getActiveScenarios,
  setActiveScenarios,
} from '../../../lib/server-scenario-state.ts';

type ScenarioControlRequest = {
  scenarios?: unknown;
};

export async function GET(): Promise<Response> {
  return Response.json({ scenarios: getActiveScenarios() });
}

export async function PUT(request: Request): Promise<Response> {
  let body: ScenarioControlRequest;
  try {
    body = (await request.json()) as ScenarioControlRequest;
  } catch {
    return Response.json({ error: 'invalid_json' }, { status: 400 });
  }
  if (
    !Array.isArray(body.scenarios) ||
    !body.scenarios.length ||
    body.scenarios.some((scenario) => !isScenarioId(scenario))
  ) {
    return Response.json({ error: 'invalid_scenarios' }, { status: 400 });
  }
  return Response.json({
    scenarios: setActiveScenarios(body.scenarios),
  });
}
