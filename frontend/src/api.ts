export type Line = { line_id: number; name: string; part_number: string };
export type Meta = { latest_date: string; lines: Line[]; shifts: Record<string, string>; llm_configured: boolean };

export type Kpis = {
  units: number; planned_units: number; attainment_pct: number | null;
  earned_hours: number; labor_hours: number; realization_pct: number | null;
  nc_count: number; first_pass_yield_pct: number | null; downtime_min: number; anomalies: number;
};

export type Anomaly = {
  anomaly_id: number; shift_date: string; shift: string; line_id: number; line: string; station: string;
  score: number; units: number; cycle_ratio: number; avg_queue_min: number; nc_count: number;
  downtime_min: number; reason: string;
};

export type ThroughputDay = { date: string; planned: number } & Record<string, number | string>;

export type NLQResult = {
  question: string; sql: string; executed_sql: string; explanation: string;
  columns: string[]; rows: unknown[][]; row_count: number; truncated: boolean;
};

export type Baseline = {
  line_id: number; line: string; window: { start: string; end: string; days: number };
  stations: number; std_cycle_min: number; std_hours_per_unit: number; efficiency: number;
  headcount: number; downtime_min: number; cycle_time_min: number; planned_units: number; actual_units: number;
};

export type SimPoint = {
  hour: number; projected_units: number; target_units: number;
  projected_earned_hours: number; target_earned_hours: number;
};
export type SimResult = {
  projected_units: number; target_units: number; gap_units: number; attainment_pct: number | null;
  earned_hours: number; target_earned_hours: number; labor_hours: number; realization_pct: number | null;
  headcount_to_hit_target: number | null; series: SimPoint[];
};

export type ShiftDetail = {
  date: string; shift: string; line_id: number | null; kpis: Kpis;
  lines: { line_id: number; name: string; headcount: number; planned_units: number; units: number;
           earned_hours: number; nc_count: number; downtime_min: number }[];
  anomalies: Anomaly[];
  downtime: { reason: string; line: string; station: string; minutes: number; started_at: string }[];
  nonconformances: { nc_id: number; serial_number: string; line: string; station: string; defect_code: string;
                     description: string; severity: string; status: string }[];
  actions: string[];
};

export class ApiError extends Error {
  constructor(message: string, public status: number, public sql?: string | null) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let body: { detail?: unknown; sql?: string | null } = {};
    try { body = await res.json(); } catch { /* non-JSON error */ }
    const detail = typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(detail, res.status, body.sql);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  kpis: (days: number) => request<Kpis & { start: string; end: string }>(`/api/kpis?days=${days}`),
  throughput: (days: number) => request<ThroughputDay[]>(`/api/throughput?days=${days}`),
  anomalies: (limit = 12) => request<Anomaly[]>(`/api/anomalies?limit=${limit}`),
  ask: (question: string) => request<NLQResult>("/api/nlq", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }),
  }),
  baseline: (lineId: number) => request<Baseline>(`/api/capacity/baseline?line_id=${lineId}`),
  simulate: (body: { line_id: number; headcount: number; downtime_min: number; cycle_time_min: number;
                     target_units?: number }) =>
    request<SimResult>("/api/capacity/simulate", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  shiftReport: (q: URLSearchParams) => request<ShiftDetail>(`/api/shift-report?${q}`),
  shiftReportPdfUrl: (q: URLSearchParams) => `/api/shift-report.pdf?${q}`,
};

export const fmt = (n: number | null | undefined, digits = 0) =>
  n == null ? "n/a" : n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
