export type Unit = 'ratio' | 'ms' | 'tokens' | 'usd' | 'count' | 'index';
export type Category = 'llm' | 'rag' | 'agent';

export interface Kpi {
  key: string;
  name: string;
  category: string;
  unit: Unit;
  direction: 'higher_better' | 'lower_better' | 'neutral';
  definition: string;
  value: number | null;
  n_observations: number;
  ci: [number, number] | null;
  status: 'ok' | 'na';
  na_reason: string | null;
  coverage?: number;
}

export interface QualityComponent {
  key: string;
  name: string;
  weight: number;
  n: number;
  mean: number;
  score: number;
}
export interface QualityMissing {
  key: string;
  name: string;
  weight: number;
  reason: string;
}
export interface QualityIndex {
  value: number | null;
  na_reason: string | null;
  coverage: number;
  components: QualityComponent[];
  missing: QualityMissing[];
  method: string;
  min_coverage: number;
  min_observations: number;
}

export interface RankingRow {
  model_id: string;
  quality_index: number | null;
  coverage: number;
  na_reason: string | null;
  n_metrics: number;
  rank?: number;
}
export interface RagRow {
  model_id: string;
  retrieval: Record<string, number | null>;
  generation: Record<string, number | null>;
}
export type LlmRow = { model_id: string } & Record<string, number | string | null>;
export interface AgentOutcome {
  model_id: string;
  success: number;
  failure: number;
  unjudged: number;
}
export interface FailureClass {
  classification: string;
  count: number;
}
export interface LatencyRow {
  model_id: string;
  n: number;
  p50: number;
  p95: number;
  p99: number;
}
export interface UsageRow {
  model_id: string;
  results: number;
  tokens: number | null;
  cost_usd: number | null;
}
export interface Distribution {
  metric_key: string;
  name: string;
  bins: number[];
  counts: number[];
}
export interface CiRow {
  metric_key: string;
  name: string;
  mean: number;
  ci_low: number;
  ci_high: number;
  n: number;
}
export interface RegressionRow {
  metric_key: string;
  name: string;
  model_id: string;
  previous: number;
  latest: number;
  severity: 'critical' | 'warning';
}

export interface Charts {
  model_ranking: RankingRow[];
  rag_quality: RagRow[];
  llm_performance: LlmRow[];
  agent_outcomes: AgentOutcome[];
  failure_classification: FailureClass[];
  latency_percentiles: LatencyRow[];
  usage: UsageRow[];
  distributions: Distribution[];
  confidence_intervals: CiRow[];
  regression: RegressionRow[];
}

export interface FilterOptions {
  projects: { id: string; name: string }[];
  providers: string[];
  model_ids: string[];
  suites: string[];
  dataset_versions: string[];
  categories: string[];
  statuses: string[];
  runs: { id: string; model_id: string | null; suite: string | null; status: string; created_at: string }[];
}

export interface Overview {
  generated_at: string;
  last_event_id: number;
  catalog_version?: string;
  filters: Record<string, unknown>;
  kpis: Kpi[];
  quality_index: QualityIndex;
  charts: Charts;
  options: FilterOptions;
  has_data: boolean;
}

export interface Filters {
  project_id?: string;
  provider?: string;
  model_id?: string;
  suite?: string;
  dataset_version?: string;
  run_id?: string;
  category?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
}

export interface TrendPoint {
  t: string;
  value: number;
  n: number;
}
export interface Trends {
  metric: string;
  unit: Unit;
  bucket: string;
  series: { model_id: string; points: TrendPoint[] }[];
  na_reason: string | null;
}

export interface CaseRow {
  observation_id?: string;
  sample_id?: string | null;
  result_id?: string | null;
  run_id?: string;
  value?: number;
  raw_metric?: string;
  model_id?: string | null;
  dataset_version?: string | null;
  prompt_excerpt?: string;
  mubit_request_id?: string | null;
  status?: string | null;
  error_type?: string | null;
  evidence_ref: string;
}

export interface MetricDef {
  key: string;
  name: string;
  category: string;
  unit: Unit;
  definition: string;
  calculation: string;
  direction: string;
  kind: string;
  qi_weight: number;
  producer: string;
  method: string;
  method_version: string;
}

export interface MetricDetail {
  metric: MetricDef;
  kpi: Kpi;
  evaluation_method: { method: string; version: string; producer: string };
  trend: Trends | null;
  distribution: { bins: number[]; counts: number[] } | null;
  failed_cases: CaseRow[];
  related_cases: CaseRow[];
  models: string[];
  dataset_versions: string[];
  evidence_refs: string[];
  failure_threshold?: number;
}

export interface CatalogItem extends MetricDef {
  current: Kpi;
}
export interface MetricsCatalog {
  catalog_version: string;
  metrics: CatalogItem[];
  last_event_id: number;
}

export interface Alert {
  id: string;
  severity: 'critical' | 'warning';
  metric_key: string;
  name: string;
  model_id: string | null;
  suite: string | null;
  latest_run_id: string;
  previous_run_id: string;
  latest_mean: number;
  previous_mean: number;
  delta: number;
  testable: boolean;
  p_value: number | null;
  ci: [number, number] | null;
  message: string;
}

export interface Describe {
  n: number;
  mean: number | null;
  std: number | null;
  ci_low: number | null;
  ci_high: number | null;
}
export interface CompareTest {
  testable: boolean;
  reason?: string;
  method?: string;
  mean_difference?: number;
  p_value?: number | null;
  effect_size?: number | null;
  ci_low?: number;
  ci_high?: number;
  significant?: boolean;
}
export interface CompareRow {
  key: string;
  name: string;
  unit: Unit;
  direction: string;
  a: Describe;
  b: Describe;
  delta: number | null;
  test: CompareTest | null;
  na_reason: string | null;
}
export interface CompareResult {
  a: { filters: Record<string, string>; quality_index: QualityIndex };
  b: { filters: Record<string, string>; quality_index: QualityIndex };
  metrics: CompareRow[];
}

export interface Preferences {
  visible_kpis: string[];
  default_filters: Record<string, unknown>;
  auto_refresh: boolean;
}

export interface EvalEvent {
  id: number;
  type: string;
  run_id: string | null;
  project_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}
export interface EventsPage {
  events: EvalEvent[];
  last_event_id: number;
  resync: boolean;
}

export interface MubitStatus {
  configured: boolean;
  base_url: string;
  model: string;
  connection_active: boolean;
  message: string;
}

export interface Schedule {
  id: string;
  name: string;
  kind: string;
  enabled: boolean;
  project_id: string;
  config: Record<string, unknown>;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_skip_reason: string | null;
  max_runs_per_day: number | null;
}

// ---- Reporting studio
export type ReportTemplate = 'executive' | 'technical' | 'statistical';
export type ReportStatus = 'PENDING' | 'GENERATING' | 'COMPLETED' | 'FAILED';
export interface ReportRequest {
  title: string;
  template: ReportTemplate;
  project_id: string;
  run_ids?: string[];
  model_ids?: string[];
  date_from?: string;
  date_to?: string;
  metrics?: string[];
  charts?: string[];
  include_cases?: boolean;
}
export interface Report {
  id: string;
  title: string;
  template: ReportTemplate;
  project_id: string;
  status: ReportStatus;
  error_message: string | null;
  snapshot_id: string | null;
  created_at: string;
  artifact: { id: string; size_bytes: number; created_at: string } | null;
  config: Record<string, unknown>;
}
export interface ReportSnapshot {
  id: string;
  schema_version: string | number;
  payload: unknown;
  payload_sha256: string;
  created_at: string;
}

// ---- Video studio
export type VideoState =
  | 'QUEUED'
  | 'GENERATING_SCRIPT'
  | 'AWAITING_APPROVAL'
  | 'RENDERING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';
export interface Scene {
  id: string;
  type: string;
  title: string;
  on_screen_text: string[];
  narration: string;
  duration_seconds: number;
  metric_refs: string[];
  evidence_refs: string[];
}
export interface Storyboard {
  schema_version: string | number;
  title: string;
  executive_narrative: string;
  key_findings: { text: string; evidence_refs: string[] }[];
  chart_explanations: { chart_id: string; text: string }[];
  failure_analysis: string;
  statistical_interpretation: string;
  recommendations: { text: string; priority: string; evidence_refs: string[] }[];
  scenes: Scene[];
  total_duration_seconds: number;
}
export interface ValidationFlag {
  scene_id: string;
  type: string;
  severity: string;
  message: string;
}
export interface VideoOptions {
  duration_seconds: 60 | 120 | 180;
  mode: 'silent' | 'narrated';
  voice?: string;
  captions: boolean;
  sections: string[];
}
export interface VideoJob {
  id: string;
  report_id: string;
  state: VideoState;
  stage: string | null;
  progress: number;
  options: Partial<VideoOptions>;
  storyboard: Storyboard | null;
  storyboard_source: 'claude' | 'template' | null;
  validation: { ok: boolean; flags: ValidationFlag[] } | null;
  approved: boolean;
  error_message: string | null;
  artifact: { id: string; size_bytes: number } | null;
  created_at: string;
  updated_at: string;
}
export interface VideoCapabilities {
  tts_available: boolean;
  voices: string[];
  renderer: string;
  mubit_configured: boolean;
  max_duration_seconds: number;
}
