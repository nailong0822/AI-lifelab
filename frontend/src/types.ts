export interface Fact { value: string; source_text: string }
export interface Profile {
  background: Fact[]
  education: Fact | null
  major: Fact | null
  year?: Fact | null
  career_stage?: Fact | null
  starting_point?: Fact | null
  target: Fact
  decision_question: string
  constraints: Fact[]
  completed_actions: Fact[]
  planned_actions: Fact[]
  observed_outcomes: Fact[]
  unknowns: string[]
}
export interface Source { id: string; title: string; url: string; author: string; content_type: string }
export interface Hit { id: string; query_id: string; source_id: string; source: Source; text: string }
export interface Evidence { value: string; quote: string; hit_id: string; evidence_scope: string }
export interface MatchDimension {
  dimension: string; label: string; weight: number; level: number | null
  contribution: number; reason: string; user_facts: Fact[]; evidence_fields: string[]
}
export interface Matching {
  version: number; score: number; field_coverage: number; tier: number; tier_label: string
  dimensions: MatchDimension[]
}
export interface AnalysisStats {
  hits: number; sources: number; analyzed_sources: number; pending_sources: number
  candidates: number; cases: number; cited_sources: number
}
export interface Case {
  id: string
  title: string
  subject: string
  source: Source
  source_nature: string
  applicability: string
  matching?: Matching
  background_match?: 'close' | 'partial' | 'distant' | 'unknown'
  background_differences?: string[]
  facts: Record<string, Evidence>
  additional_evidence?: (Evidence & { field: string })[]
}
export interface SearchQuery {
  id: string; label: string; query_text: string; purpose: string; target_gap: string
  relaxed_fields: string[]; preserved_fields: Record<string, string>
  status: string; result_count: number; duration_ms: number | null; error: string | null
  requested_count?: number; relaxation_reason?: string; retry_of?: string | null
}
export interface Coverage { dimension: string; label: string; status: string; case_ids: string[] }
export interface Gap { dimension: string; description: string; kind: string }
export interface Report {
  summary: string; evidence_note: string; stop_reason: string; result_status: string
  stats: Partial<AnalysisStats> & { requests: number; hits: number; sources: number; cases: number }
}
export interface RunSummary {
  id: string; question: string; created_at: number; status: string
  result_status: string | null; stop_reason: string | null
}
export interface Run extends RunSummary {
  workflow_version?: number
  analysis_stats?: AnalysisStats | null
  profile: Profile | null
  profile_version: number
  clarification: {
    id: string; questions: { id: string; question: string; reason: string }[]
    answers: Record<string, string> | null
  } | null
  queries: SearchQuery[]
  hits: Hit[]
  cases: Case[]
  coverage: Coverage[]
  gaps: Gap[]
  request_count: number
  tokens_used: number
  tokens_estimated: boolean
  elapsed_seconds: number
  clock_started_at: number | null
  last_event_sequence: number
  report: Report | null
  error: string | null
  limits: { requests: number; tokens: number; seconds: number }
}
export interface TraceEvent {
  run_id: string; sequence: number; event_type: string; node: string; occurred_at: number
  title: string; query_id: string | null; span_id: string | null
  payload: Record<string, unknown>
}
export interface Health { status: string; model_configured: boolean; zhihu_configured: boolean; model: string }
