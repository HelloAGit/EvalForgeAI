import { authHeader, clearToken, getToken } from './auth';
import type {
  Alert, CompareResult, EventsPage, Filters, MetricDetail, MetricsCatalog, MubitStatus, Overview, Preferences,
  Report, ReportRequest, ReportSnapshot, Schedule, Trends, Scene, Storyboard, VideoCapabilities, VideoJob, VideoOptions,
} from './types';

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailToMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d)))
      .join('; ');
  }
  return fallback;
}

export async function apiRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined), ...authHeader(getToken()) };
  if (init.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, `Cannot reach the backend at ${API_BASE}.`);
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      msg = detailToMessage(body?.detail, msg);
    } catch {
      /* non-JSON body */
    }
    if (res.status === 401) {
      clearToken();
      msg = 'Authentication required: the token is missing or invalid.';
    }
    throw new ApiError(res.status, msg);
  }
  return res;
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiRequest(path, init);
  return (await res.json()) as T;
}

export async function apiBlobUrl(path: string): Promise<{ url: string; size: number }> {
  const res = await apiRequest(path);
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), size: blob.size };
}

export function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

const jsonBody = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const fetchOverview = (f: Filters, signal?: AbortSignal) =>
  apiJson<Overview>(`/api/v1/dashboard/overview${buildQuery({ ...f })}`, { signal });
export const fetchTrends = (f: Filters, metric: string, bucket: 'day' | 'hour', signal?: AbortSignal) =>
  apiJson<Trends>(`/api/v1/dashboard/trends${buildQuery({ ...f, metric, bucket })}`, { signal });
export const fetchMetricDetail = (key: string, f: Filters, signal?: AbortSignal) =>
  apiJson<MetricDetail>(`/api/v1/dashboard/metrics/${encodeURIComponent(key)}${buildQuery({ ...f })}`, { signal });
export const fetchMetricsCatalog = (f: Filters = {}) =>
  apiJson<MetricsCatalog>(`/api/v1/dashboard/metrics${buildQuery({ ...f })}`);
export const fetchAlerts = (f: Filters, signal?: AbortSignal) =>
  apiJson<{ alerts: Alert[]; threshold: number }>(`/api/v1/dashboard/alerts${buildQuery({ ...f })}`, { signal });
export const fetchCompare = (side: { a: Record<string, string>; b: Record<string, string> }, f: Filters) =>
  apiJson<CompareResult>(
    `/api/v1/dashboard/compare${buildQuery({
      ...f,
      a_model_id: side.a.model_id, a_run_id: side.a.run_id, b_model_id: side.b.model_id, b_run_id: side.b.run_id,
    })}`,
  );
export const fetchPreferences = () => apiJson<Preferences>('/api/v1/dashboard/preferences');
export const savePreferences = (p: Preferences) => apiJson<Preferences>('/api/v1/dashboard/preferences', jsonBody('PUT', p));
export const fetchMubitStatus = () => apiJson<MubitStatus>('/api/v1/mubit/status');
export const fetchEventsPage = (after: number, signal?: AbortSignal) =>
  apiJson<EventsPage>(`/api/v1/dashboard/events${buildQuery({ after })}`, { signal });

export const listSchedules = () => apiJson<Schedule[]>('/api/v1/schedules');
export const setScheduleEnabled = (id: string, enabled: boolean) =>
  apiJson<Schedule>(`/api/v1/schedules/${encodeURIComponent(id)}/${enabled ? 'enable' : 'disable'}`, jsonBody('POST'));

// Reports
export const createReport = (b: ReportRequest) => apiJson<Report>('/api/v1/reports', jsonBody('POST', b));
export const previewReport = (b: ReportRequest) => apiJson<{ payload: unknown }>('/api/v1/reports/preview', jsonBody('POST', b));
export const listReports = () => apiJson<Report[]>('/api/v1/reports');
export const getReport = (id: string) => apiJson<Report>(`/api/v1/reports/${encodeURIComponent(id)}`);
export const regenerateReport = (id: string) =>
  apiJson<Report>(`/api/v1/reports/${encodeURIComponent(id)}/regenerate`, jsonBody('POST'));
export const getReportSnapshot = (id: string) => apiJson<ReportSnapshot>(`/api/v1/reports/${encodeURIComponent(id)}/snapshot`);
export const reportPdfUrl = (id: string) => apiBlobUrl(`/api/v1/reports/${encodeURIComponent(id)}/download`);

// Videos
export const createVideo = (b: { report_id: string } & VideoOptions) => apiJson<VideoJob>('/api/v1/videos', jsonBody('POST', b));
export const listVideos = () => apiJson<VideoJob[]>('/api/v1/videos');
export const getVideo = (id: string) => apiJson<VideoJob>(`/api/v1/videos/${encodeURIComponent(id)}`);
export const getVideoCapabilities = () => apiJson<VideoCapabilities>('/api/v1/videos/capabilities');
export const saveStoryboard = (id: string, storyboard: Storyboard) =>
  apiJson<VideoJob>(`/api/v1/videos/${encodeURIComponent(id)}/storyboard`, jsonBody('PUT', { storyboard }));
export const approveVideo = (id: string, acknowledge_flags: boolean) =>
  apiJson<VideoJob>(`/api/v1/videos/${encodeURIComponent(id)}/approve`, jsonBody('POST', { acknowledge_flags }));
export const renderVideo = (id: string) => apiJson<VideoJob>(`/api/v1/videos/${encodeURIComponent(id)}/render`, jsonBody('POST'));
export const cancelVideo = (id: string) => apiJson<VideoJob>(`/api/v1/videos/${encodeURIComponent(id)}/cancel`, jsonBody('POST'));
export const videoMp4Url = (id: string) => apiBlobUrl(`/api/v1/videos/${encodeURIComponent(id)}/download`);

export type { Scene };
