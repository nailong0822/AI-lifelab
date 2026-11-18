export interface Basis { kind: 'case' | 'synthesis' | 'hypothesis'; explanation: string; evidence_ids: string[]; validation_action: string }
export interface Candidate { id: string; title: string; goal: string; approach: string; suitable_conditions: string[]; first_action: string; effort: string; difficulties: string[]; basis: Basis }
export interface PathTask { id: string; title: string; kind: string; description: string; output: string; completion_criteria: string; depends_on: string[]; effort_hours: number | null; skills: string[]; help_hint: string; basis: Basis }
export interface Stage { id: string; title: string; objective: string; completion_criteria: string; depends_on: string[]; effort_hours_min: number | null; effort_hours_max: number | null; already_completed: boolean; basis: Basis; tasks: PathTask[] }
export interface Plan { title: string; goal: string; stages: Stage[]; limitations: string[]; version: number }
export interface PathRun {
  id: string; retrieval_run_id: string; status: string; question: string; version: number; journey_status: string;
  candidates: Candidate[]; plan: Plan | null; pending_revision: Plan | null; current_stage_id: string | null;
  progress: Record<string, {status: string; note: string}>;
  versions: {version: number; title: string; reason: string}[];
  evidence_catalog: Record<string, {id: string; quote: string; value: string; source: {title?: string; url?: string}}>;
  completed_work: {id: string; title: string; skills: string[]; note: string}[];
  input_request: {id: string; kind: string; data: {questions?: {id: string; question: string; reason: string}[]}} | null;
  operation: {kind: string; tokens_used: number; elapsed_seconds: number; limits: {tokens: number; seconds: number}} | null;
  error: string | null;
}
export interface PathEvent { sequence: number; title: string; node: string; occurred_at: number; payload: Record<string, unknown> }
