"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  RefreshCw, Moon, AlertTriangle, CheckCircle2, Play,
  Zap, Info, SkipForward, ChevronDown, ChevronRight
} from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function fmt(ts: string | null | undefined) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

function fmtGbp(v: number | null | undefined) {
  if (v == null) return "—";
  return `£${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function elapsed(start: string, end: string | null) {
  if (!start || !end) return "";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return ms < 60000 ? `${(ms / 1000).toFixed(1)}s` : `${(ms / 60000).toFixed(1)}m`;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; icon: React.ReactNode; label: string }> = {
    success:       { cls: "bg-green-500/10 text-green-400 border-green-500/20",   icon: <CheckCircle2 className="w-3 h-3" />, label: "Success" },
    error:         { cls: "bg-red-500/10 text-red-400 border-red-500/20",         icon: <AlertTriangle className="w-3 h-3" />, label: "Error" },
    partial_error: { cls: "bg-amber-500/10 text-amber-400 border-amber-500/20",   icon: <AlertTriangle className="w-3 h-3" />, label: "Partial Error" },
    skipped:       { cls: "bg-blue-500/10 text-blue-400 border-blue-500/20",      icon: <SkipForward className="w-3 h-3" />, label: "Skipped (freshness)" },
    unknown:       { cls: "bg-[var(--slate)]/10 text-[var(--slate)] border-[var(--slate)]/20", icon: <Info className="w-3 h-3" />, label: "Unknown" },
  };
  const s = map[status] ?? map.unknown;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wider ${s.cls}`}>
      {s.icon}{s.label}
    </span>
  );
}

function AccountDetailCard({ entry }: { entry: any }) {
  const sourceCounts = entry.price_sources ?? {};
  const total = Object.values(sourceCounts).reduce((a: any, b: any) => a + b, 0) as number;

  return (
    <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm font-semibold text-[var(--foreground)]">{entry.account}</span>
        <StatusBadge status={entry.status} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div className="bg-[var(--background)] rounded p-2.5 border border-[var(--border-color)]">
          <div className="text-[var(--slate)] uppercase tracking-wider text-[10px] mb-1">Final Cash</div>
          <div className={`font-mono font-semibold ${entry.final_cash == null ? "text-[var(--slate)]" : entry.final_cash < 0 ? "text-red-400" : "text-green-400"}`}>
            {fmtGbp(entry.final_cash)}
          </div>
        </div>
        <div className="bg-[var(--background)] rounded p-2.5 border border-[var(--border-color)]">
          <div className="text-[var(--slate)] uppercase tracking-wider text-[10px] mb-1">Final Equity</div>
          <div className="font-mono font-semibold text-[var(--foreground)]">{fmtGbp(entry.final_equity)}</div>
        </div>
        <div className="bg-[var(--background)] rounded p-2.5 border border-[var(--border-color)]">
          <div className="text-[var(--slate)] uppercase tracking-wider text-[10px] mb-1">Total NAV</div>
          <div className="font-mono font-semibold text-[var(--foreground)]">{fmtGbp(entry.final_total_nav)}</div>
        </div>
        <div className="bg-[var(--background)] rounded p-2.5 border border-[var(--border-color)]">
          <div className="text-[var(--slate)] uppercase tracking-wider text-[10px] mb-1">Duration</div>
          <div className="font-mono text-[var(--foreground)]">{elapsed(entry.start_time, entry.end_time) || "—"}</div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div className="bg-[var(--background)] rounded p-2.5 border border-[var(--border-color)]">
          <div className="text-[var(--slate)] uppercase tracking-wider text-[10px] mb-1">Snap Cash</div>
          <div className="font-mono text-[var(--foreground)]">{entry.snap_cash != null ? `£${Number(entry.snap_cash).toFixed(2)}` : "—"}</div>
        </div>
        <div className="bg-[var(--background)] rounded p-2.5 border border-[var(--border-color)]">
          <div className="text-[var(--slate)] uppercase tracking-wider text-[10px] mb-1">Snap Qty Count</div>
          <div className="font-mono text-[var(--foreground)]">{entry.snap_qty_count ?? "—"}</div>
        </div>
        <div className="bg-[var(--background)] rounded p-2.5 border border-[var(--border-color)]">
          <div className="text-[var(--slate)] uppercase tracking-wider text-[10px] mb-1">Legacy Adj</div>
          <div className="font-mono text-[var(--foreground)]">{entry.legacy_adj != null ? `£${Number(entry.legacy_adj).toFixed(2)}` : "—"}</div>
        </div>
        <div className="bg-[var(--background)] rounded p-2.5 border border-[var(--border-color)]">
          <div className="text-[var(--slate)] uppercase tracking-wider text-[10px] mb-1">Force Full Prices</div>
          <div className={`font-mono font-semibold ${entry.force_full_prices ? "text-amber-400" : "text-[var(--slate)]"}`}>
            {entry.force_full_prices ? "YES (Repair)" : "NO (Incremental)"}
          </div>
        </div>
      </div>

      {total > 0 && (
        <div className="bg-[var(--background)] rounded p-3 border border-[var(--border-color)]">
          <div className="text-[var(--slate)] uppercase tracking-wider text-[10px] mb-2">Price Sources ({entry.ticker_count ?? total} tickers)</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(sourceCounts).map(([src, cnt]: [string, any]) => {
              const pct = total > 0 ? Math.round((cnt / total) * 100) : 0;
              const color = src === "Failed" ? "text-red-400 bg-red-500/10 border-red-500/20"
                          : src === "Yahoo"  ? "text-amber-400 bg-amber-500/10 border-amber-500/20"
                          :                    "text-green-400 bg-green-500/10 border-green-500/20";
              return (
                <span key={src} className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-mono ${color}`}>
                  <span className="font-semibold">{src}</span>
                  <span className="opacity-70">{cnt} ({pct}%)</span>
                </span>
              );
            })}
          </div>
        </div>
      )}

      {entry.multiplier_anomalies && Object.keys(entry.multiplier_anomalies).length > 0 && (
        <div className="bg-amber-500/5 border border-amber-500/20 rounded p-3">
          <div className="text-amber-400 text-[10px] uppercase tracking-wider font-semibold mb-1.5 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> Price Multiplier Anomalies (non-1.0)
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(entry.multiplier_anomalies).map(([t, m]: [string, any]) => (
              <span key={t} className="font-mono text-xs bg-amber-500/10 text-amber-300 px-2 py-0.5 rounded">
                {t}: ×{m}
              </span>
            ))}
          </div>
        </div>
      )}

      {entry.rows_written != null && (
        <div className="text-xs text-[var(--slate)]">
          <span className="font-mono">{entry.rows_written}</span> rows written to DB
          {entry.snapshot_date && <span> · snapshot date: <span className="font-mono">{entry.snapshot_date}</span></span>}
        </div>
      )}

      {entry.error && (
        <div className="bg-red-500/5 border border-red-500/20 rounded p-3">
          <div className="text-red-400 text-[10px] uppercase tracking-wider font-semibold mb-1">Error</div>
          <pre className="text-red-300 text-xs whitespace-pre-wrap break-all leading-relaxed">{entry.error}</pre>
          {entry.traceback && (
            <details className="mt-2">
              <summary className="text-[var(--slate)] text-[10px] cursor-pointer hover:text-red-300 transition-colors">Show traceback</summary>
              <pre className="mt-1 text-[10px] text-[var(--slate)] whitespace-pre-wrap break-all">{entry.traceback}</pre>
            </details>
          )}
        </div>
      )}

      {entry.audit_read_error && (
        <div className="text-xs text-amber-400/70 italic">Note: Audit read error — {entry.audit_read_error}</div>
      )}
    </div>
  );
}

function RunEntryRow({ entry, index }: { entry: any; index: number }) {
  const [expanded, setExpanded] = useState(index === 0);
  const accounts: any[] = entry.accounts_processed ?? [];
  const hasErrors = accounts.some((a: any) => a.status === "error");

  return (
    <div className="border border-[var(--border-color)] rounded-lg overflow-hidden transition-all">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 bg-[var(--background)] hover:bg-[var(--card-bg)] transition-colors text-left"
      >
        {expanded ? <ChevronDown className="w-4 h-4 text-[var(--slate)] flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-[var(--slate)] flex-shrink-0" />}

        <div className="flex-1 grid grid-cols-2 md:grid-cols-5 gap-3 items-center">
          <div className="col-span-2 md:col-span-1">
            <div className="text-xs text-[var(--slate)]">Started</div>
            <div className="font-mono text-[10px] text-[var(--foreground)]">{fmt(entry.run_start)}</div>
          </div>
          <div>
            <StatusBadge status={entry.overall_status} />
          </div>
          <div className="hidden md:block">
            <div className="text-xs text-[var(--slate)]">Triggered by</div>
            <div className="text-[10px] font-mono text-[var(--foreground)] truncate">{entry.triggered_by}</div>
          </div>
          <div className="hidden md:block">
            <div className="text-xs text-[var(--slate)]">Accounts</div>
            <div className="text-[10px] font-mono text-[var(--foreground)]">
              {accounts.length > 0 ? accounts.map((a: any) => a.account).join(", ") : (entry.freshness_skipped ? "skipped" : "—")}
            </div>
          </div>
          <div className="hidden md:block">
            <div className="text-xs text-[var(--slate)]">Duration</div>
            <div className="text-[10px] font-mono text-[var(--foreground)]">{elapsed(entry.run_start, entry.run_end)}</div>
          </div>
        </div>

        {hasErrors && <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />}
        {entry.freshness_skipped && <SkipForward className="w-4 h-4 text-blue-400 flex-shrink-0" title="Freshness check — already ran today" />}
      </button>

      {expanded && (
        <div className="p-4 bg-[var(--card-bg)] border-t border-[var(--border-color)] space-y-3">
          <div className="flex flex-wrap gap-3 text-xs text-[var(--slate)]">
            {entry.db_sync_outcome && (
              <span className="bg-[var(--background)] px-2 py-1 rounded border border-[var(--border-color)] font-mono">
                DB sync: {entry.db_sync_outcome}
              </span>
            )}
            {entry.cache_cleared != null && (
              <span className={`px-2 py-1 rounded border text-[10px] font-semibold ${
                entry.cache_cleared
                  ? "bg-green-500/10 text-green-400 border-green-500/20"
                  : "bg-red-500/10 text-red-400 border-red-500/20"
              }`}>
                {entry.cache_cleared ? "✓ GSheet cache cleared" : "✗ GSheet cache NOT cleared"}
              </span>
            )}
            {entry.freshness_skipped && (
              <span className="bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-1 rounded text-[10px] font-semibold">
                ⚡ Freshness check fired — skipped all accounts (already ran today)
              </span>
            )}
            {entry.freshness_check_error && (
              <span className="bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-1 rounded text-[10px]">
                Freshness check error: {entry.freshness_check_error}
              </span>
            )}
            {entry.account_order && (
              <span className="bg-[var(--background)] px-2 py-1 rounded border border-[var(--border-color)] font-mono text-[10px]">
                Order: {entry.account_order.join(" → ")}
              </span>
            )}
          </div>

          {accounts.length > 0 ? (
            <div className="space-y-3">
              {accounts.map((a: any, i: number) => <AccountDetailCard key={i} entry={a} />)}
            </div>
          ) : entry.freshness_skipped ? (
            <div className="text-sm text-blue-400/80 italic p-4 bg-blue-500/5 border border-blue-500/10 rounded-lg">
              No accounts were processed — the scheduler detected that a run already occurred today and skipped recalculation.
              To force a run, use the "Trigger Dry Run" button below.
            </div>
          ) : (
            <div className="text-sm text-[var(--slate)] italic">No per-account data captured.</div>
          )}
        </div>
      )}
    </div>
  );
}

export function NightlyRunLog() {
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [forceFullPrices, setForceFullPrices] = useState(false);
  const [bypassFreshness, setBypassFreshness] = useState(false);
  const [lastRunResult, setLastRunResult] = useState<any>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const fetchLog = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const res = await fetch(`${API}/api/system/nightly-log`);
      if (res.ok) {
        const d = await res.json();
        setEntries(d.entries ?? []);
      } else {
        const body = await res.text().catch(() => "");
        setFetchError(`Server error ${res.status}: ${body || res.statusText}`);
      }
    } catch (e: any) {
      console.error(e);
      setFetchError(
        e?.message === "Failed to fetch"
          ? `Cannot reach backend at ${API}. Is the server running?`
          : String(e?.message ?? e)
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLog();
    const interval = setInterval(fetchLog, 60000);
    return () => clearInterval(interval);
  }, [fetchLog]);

  const triggerDryRun = async () => {
    setRunning(true);
    setLastRunResult(null);
    try {
      const res = await fetch(`${API}/api/system/trigger-nightly-dry-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force_full_prices: forceFullPrices, bypass_freshness: bypassFreshness }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Dry run failed");
      setLastRunResult(data);
      await fetchLog();
    } catch (e: any) {
      setLastRunResult({ status: "error", errors: [e.message] });
    } finally {
      setRunning(false);
    }
  };

  // Only alert red if the LATEST run had a conflict; older entries are historical noise
  const latestEntry = entries[0] ?? null;
  const latestHasConflict = latestEntry?.streamlit_scheduler_also_enabled === true;
  const pastConflictCount = entries.slice(1).filter((e: any) => e.streamlit_scheduler_also_enabled).length;

  return (
    <section className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h3 className="text-lg font-medium text-[var(--foreground)] border-l-2 border-brand-gold pl-3 flex items-center gap-2">
            <Moon className="w-5 h-5 text-brand-gold" /> Nightly Auto-Refresh Log
          </h3>
          <p className="text-xs text-[var(--slate)] mt-1 ml-5">
            Structured diagnostic log of every nightly recalculation. Captures cash, equity, price sources, and more per account.
            Auto-refreshes every 60s.
          </p>
        </div>
        <button onClick={fetchLog} className="text-[var(--slate)] hover:text-brand-gold transition-colors" title="Refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {fetchError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-sm text-red-300">
          <span className="font-semibold text-red-400">Failed to load log: </span>{fetchError}
        </div>
      )}

      {/* Only show the alarming red banner if the MOST RECENT run still had a conflict */}
      {latestHasConflict && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <div className="text-sm font-semibold text-red-400 mb-1">⚠ Scheduler Conflict — Still Active</div>
            <p className="text-xs text-red-300/80 leading-relaxed">
              The most recent run detected both the Streamlit and backend schedulers running simultaneously.
              Both were writing to the same SQLite database — the last one to finish overwrote the other's results.
            </p>
            <p className="text-xs text-red-300/60 mt-2">
              <strong className="text-red-300">Action needed:</strong> Disable auto-refresh in the old Streamlit sidebar,
              or verify that <code className="font-mono bg-red-500/10 px-1 rounded">auto_refresh_enabled</code> is <code className="font-mono bg-red-500/10 px-1 rounded">false</code> in <code className="font-mono bg-red-500/10 px-1 rounded">newsletter_schedule.json</code>.
            </p>
          </div>
        </div>
      )}

      {/* Dimmer note for historical conflicts when the latest run is clean */}
      {!latestHasConflict && pastConflictCount > 0 && (
        <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg px-4 py-3 flex items-center gap-3">
          <CheckCircle2 className="w-4 h-4 text-green-400 flex-shrink-0" />
          <p className="text-xs text-[var(--slate)]">
            <span className="text-green-400 font-semibold">Conflict resolved.</span> {pastConflictCount} older log {pastConflictCount === 1 ? "entry" : "entries"} recorded a scheduler conflict,
            but the most recent run completed cleanly with no conflict detected. The fix is working.
          </p>
        </div>
      )}

      <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-xl p-5">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-9 h-9 rounded-full bg-brand-gold/10 flex items-center justify-center flex-shrink-0">
            <Zap className="w-4 h-4 text-brand-gold" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-[var(--foreground)]">Trigger Diagnostic Run</h4>
            <p className="text-xs text-[var(--slate)] mt-0.5">
              Run the recalculation pipeline now and capture a detailed log entry. Compare <strong className="text-[var(--foreground)]">Incremental</strong> (nightly mode) vs <strong className="text-amber-400">Force Full</strong> (repair mode) to identify discrepancies.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-3">
          {/* Toggle row */}
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <div
                onClick={() => setForceFullPrices(f => !f)}
                className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${forceFullPrices ? "bg-amber-500" : "bg-[var(--border-color)]"}`}
              >
                <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${forceFullPrices ? "translate-x-5" : "translate-x-0.5"}`} />
              </div>
              <span className="text-sm text-[var(--foreground)]">
                {forceFullPrices
                  ? <><span className="text-amber-400 font-semibold">Force Full Prices</span> <span className="text-[var(--slate)] text-xs">(re-downloads all 8yr history)</span></>
                  : <><span className="text-[var(--foreground)]">Incremental Prices</span> <span className="text-[var(--slate)] text-xs">(cache flush only — closest to nightly run)</span></>
                }
              </span>
            </label>

            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <div
                onClick={() => setBypassFreshness(f => !f)}
                className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${bypassFreshness ? "bg-sky-500" : "bg-[var(--border-color)]"}`}
              >
                <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${bypassFreshness ? "translate-x-5" : "translate-x-0.5"}`} />
              </div>
              <span className="text-sm text-[var(--foreground)]">
                {bypassFreshness
                  ? <><span className="text-sky-400 font-semibold">Bypass Freshness</span> <span className="text-[var(--slate)] text-xs">(run even if already ran today)</span></>
                  : <><span className="text-[var(--foreground)]">Respect Freshness</span> <span className="text-[var(--slate)] text-xs">(skip if already ran today)</span></>
                }
              </span>
            </label>
          </div>

          {/* Run button */}
          <div>
            <button
              onClick={triggerDryRun}
              disabled={running}
              className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 ${
                forceFullPrices
                  ? "bg-amber-500 hover:bg-amber-600 text-black"
                  : bypassFreshness
                  ? "bg-sky-500 hover:bg-sky-600 text-white"
                  : "bg-brand-gold hover:bg-[#b58b38] text-[var(--background)]"
              }`}
            >
              {running ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {running ? "Running…" : forceFullPrices ? "Trigger Full Run" : bypassFreshness ? "Trigger Incremental (Force)" : "Trigger Run"}
            </button>
          </div>
        </div>

        {lastRunResult && !running && (
          <div className={`mt-4 p-3 rounded-lg border text-sm ${
            lastRunResult.status === "success"
              ? "bg-green-500/5 border-green-500/20 text-green-400"
              : "bg-red-500/5 border-red-500/20 text-red-400"
          }`}>
            {lastRunResult.status === "success"
              ? "✓ Run completed successfully — scroll down to see the new log entry."
              : `✗ Run encountered errors: ${(lastRunResult.errors ?? []).join("; ")}`}
          </div>
        )}
      </div>

      {entries.length === 0 ? (
        <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-xl p-10 text-center">
          <Moon className="w-8 h-8 text-[var(--slate)]/40 mx-auto mb-3" />
          <p className="text-sm text-[var(--slate)]">No nightly run entries recorded yet.</p>
          <p className="text-xs text-[var(--slate)]/60 mt-1">
            Entries appear here after the first auto-refresh or after triggering a dry run above.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map((entry: any, i: number) => (
            <RunEntryRow key={i} entry={entry} index={i} />
          ))}
        </div>
      )}
    </section>
  );
}
