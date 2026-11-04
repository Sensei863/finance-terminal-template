/**
 * Shared Quantitative Terminal Domain Interfaces
 */

export interface Account {
  name: string;
  classification: "Live" | "Playground" | "Archived" | string;
  baseCurrency?: string;
  worksheet?: string;
  legacyCashAdjustment?: number;
}

export interface SyntheticBenchmark {
  name: string;
  constituents: Record<string, number>;
  rebalanceFreq?: string;
  created_at?: string;
  updated_at?: string;
}

export interface NightlyRunLogEntry {
  run_start: string;
  run_end: string | null;
  triggered_by: "scheduler" | "dry_run" | "manual" | string;
  force_full_prices: boolean;
  freshness_skipped: boolean;
  cache_cleared: boolean;
  owner: string;
  pid: number;
  accounts_processed: string[];
  overall_status: "success" | "error" | "unknown";
  overall_error?: string;
  db_sync_outcome?: unknown;
}

export interface AutoRefreshConfig {
  auto_refresh_enabled: boolean;
  auto_refresh_hour: number;
  auto_refresh_minute: number;
  auto_refresh_last_run?: string;
  auto_refresh_last_status?: "success" | "error" | string;
  auto_refresh_last_error?: string | null;
  is_running?: boolean;
}

export interface NewsletterProductSchedule {
  day: string;
  hour: number;
  minute: number;
  enabled: boolean;
  refresh_hours: number;
  additional_recipients: string;
}

export interface NewsletterProduct {
  product_id: string;
  name: string;
  accounts: string[];
  synthetic_benchmark?: string;
  benchmark_label?: string;
  schedule?: NewsletterProductSchedule;
  last_sent?: string;
  subject_template?: string;
  recipients?: string[];
  language?: string;
  output_filename?: string;
}

export interface SnapshotMeta {
  name: string;
  date: string;
  path: string;
  folder?: string;
  available_files?: string[];
}

export interface StorageRunLogEntry {
  account?: string;
  run_type?: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface PositionHolding {
  ticker: string;
  shares: number;
  price: number;
  value: number;
  weight: number;
  asset_class?: string;
}

export interface PortfolioPerformancePoint {
  Date: string;
  Equity: number;
  Cash: number;
  "Total NAV": number;
  TWR_Index: number;
  Net_Invested: number;
  Daily_Return?: number;
  Bench_NAV?: number;
}
