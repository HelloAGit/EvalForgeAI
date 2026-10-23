import { DashboardSummary, MubitStatus } from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/dashboard/summary`);
    if (!res.ok) throw new Error('Failed to fetch summary');
    return await res.json();
  } catch {
    return {
      quality_index: 88.4,
      total_evaluations: 1240,
      llm_correctness: 91.2,
      rag_faithfulness: 86.5,
      agent_completion: 87.8,
      verified_failures: 42,
      avg_latency_ms: 340,
      eval_cost_usd: 12.45,
      is_demo_data: true
    };
  }
}

export async function fetchMubitStatus(): Promise<MubitStatus> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/mubit/status`);
    if (!res.ok) throw new Error('Failed to fetch Mubit status');
    return await res.json();
  } catch {
    return {
      configured: false,
      base_url: 'https://api.mubit.ai/anthropic',
      model: 'claude-haiku-4-5',
      connection_active: false,
      message: 'Backend unreachable'
    };
  }
}
