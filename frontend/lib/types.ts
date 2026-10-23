export interface DashboardSummary {
  quality_index: number;
  total_evaluations: number;
  llm_correctness: number;
  rag_faithfulness: number;
  agent_completion: number;
  verified_failures: number;
  avg_latency_ms: number;
  eval_cost_usd: number;
  is_demo_data: boolean;
}

export interface MubitStatus {
  configured: boolean;
  base_url: string;
  model: string;
  connection_active: boolean;
  message: string;
}
