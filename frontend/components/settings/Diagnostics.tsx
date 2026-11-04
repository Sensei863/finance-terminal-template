"use client";

import React, { useState, useEffect } from "react";
import { Activity, Search, RefreshCw, Calendar, Save } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function Diagnostics() {
  const [account, setAccount] = useState("ISA");
  
  // Section 1: Portfolio Composition
  const [asOfDate, setAsOfDate] = useState(new Date().toISOString().split('T')[0]);
  const [compData, setCompData] = useState<any>(null);
  const [compLoading, setCompLoading] = useState(false);

  // Section 2: Ledger Search
  const [searchTicker, setSearchTicker] = useState("");
  const [ledgerRows, setLedgerRows] = useState<any[]>([]);
  const [ledgerLoading, setLedgerLoading] = useState(false);

  // Section 3: Engine Audit
  const [auditData, setAuditData] = useState<any>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);

  // Section 4: Run Logs
  const [runLogs, setRunLogs] = useState<any[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);

  // Section 5: Legacy Adj
  const [legacyAdj, setLegacyAdj] = useState<number>(0);
  const [isSavingAdj, setIsSavingAdj] = useState(false);

  // Data Fetchers
  const fetchComposition = async () => {
    if (!asOfDate) return;
    setCompLoading(true);
    try {
      const res = await fetch(`${API}/api/diagnostics/composition?account=${account}&as_of=${asOfDate}`);
      if (res.ok) setCompData(await res.json());
    } catch (e) {
      console.error(e);
    } finally {
      setCompLoading(false);
    }
  };

  const fetchLedgerRows = async () => {
    if (!searchTicker) return;
    setLedgerLoading(true);
    try {
      const res = await fetch(`${API}/api/diagnostics/ledger_rows?account=${account}&ticker=${searchTicker}`);
      if (res.ok) {
        const data = await res.json();
        setLedgerRows(data.rows || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLedgerLoading(false);
    }
  };

  const fetchAudit = async () => {
    setAuditLoading(true);
    setAuditError(null);
    try {
      const res = await fetch(`${API}/api/diagnostics/audit?account=${account}`);
      if (res.ok) {
        setAuditData(await res.json());
      } else {
        const body = await res.text().catch(() => "");
        setAuditError(`Server error ${res.status}: ${body || res.statusText}`);
      }
    } catch (e: any) {
      console.error(e);
      setAuditError(
        e?.message === "Failed to fetch"
          ? `Cannot reach backend at ${API}. Is the server running?`
          : String(e?.message ?? e)
      );
    } finally {
      setAuditLoading(false);
    }
  };

  const fetchLogs = async () => {
    setLogsLoading(true);
    try {
      const res = await fetch(`${API}/api/diagnostics/run_log?limit=30`);
      if (res.ok) {
        const data = await res.json();
        setRunLogs(data.logs || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLogsLoading(false);
    }
  };

  const fetchLegacyAdj = async () => {
    try {
      const res = await fetch(`${API}/api/portfolio/legacy-adjustment?account=${encodeURIComponent(account)}`);
      if (res.ok) {
        const d = await res.json();
        setLegacyAdj(d.adjustment);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleSaveAdj = async () => {
    setIsSavingAdj(true);
    try {
      const res = await fetch(`${API}/api/portfolio/legacy-adjustment`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account, adjustment: legacyAdj })
      });
      if (!res.ok) throw new Error("Failed to save adjustment");
      alert("Adjustment saved! Recalculate the engine to apply it.");
    } catch (e: any) {
      alert(e.message);
    } finally {
      setIsSavingAdj(false);
    }
  };

  // Initial load
  useEffect(() => {
    fetchAudit();
    fetchLogs();
    fetchLegacyAdj();
  }, [account]);

  return (
    <div className="space-y-12 animate-in fade-in slide-in-from-bottom-4 duration-500">
      
      {/* Header & Global Selectors */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[var(--border-color)] pb-6">
        <div>
          <h2 className="text-2xl font-serif text-[var(--foreground)] mb-2 flex items-center gap-2">
            <Activity className="w-5 h-5 text-brand-gold" />
            Diagnostics &amp; Toolkit
          </h2>
          <p className="text-sm text-[var(--slate)]">Engine audit, ledger deep-dives, and performance tracking.</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-sm text-[var(--slate)] uppercase tracking-wider font-semibold">Account</label>
          <select 
            value={account} 
            onChange={(e) => setAccount(e.target.value)}
            className="bg-[var(--background)] border border-[var(--border-color)] rounded-md px-4 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:border-brand-gold min-w-[150px]"
          >
            <option value="ISA">ISA</option>
            <option value="SIPP">SIPP</option>
            <option value="Consolidated">Consolidated</option>
          </select>
        </div>
      </div>

      {/* ─── Divider ─── */}
      <div className="border-t border-[var(--border-color)] pt-2">
        <p className="text-xs text-[var(--slate)] uppercase tracking-wider font-semibold">Account-Level Tools (select account above)</p>
      </div>

      {/* 1. Portfolio Composition */}
      <section className="space-y-4">
        <h3 className="text-lg font-medium text-[var(--foreground)] border-l-2 border-brand-gold pl-3">Portfolio Composition (As of Date)</h3>
        <div className="flex flex-col md:flex-row gap-4 mb-4">
          <div className="flex items-center gap-2 bg-[var(--background)] border border-[var(--border-color)] rounded-md px-3 py-1.5 focus-within:border-brand-gold transition-colors">
            <Calendar className="w-4 h-4 text-[var(--slate)]" />
            <input 
              type="date" 
              value={asOfDate} 
              onChange={(e) => setAsOfDate(e.target.value)}
              className="bg-transparent text-sm text-[var(--foreground)] focus:outline-none"
            />
          </div>
          <button 
            onClick={fetchComposition}
            disabled={compLoading}
            className="bg-[var(--background)] border border-[var(--border-color)] hover:border-brand-gold text-[var(--foreground)] px-4 py-1.5 rounded-md text-sm transition-colors flex items-center gap-2"
          >
            {compLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : "Calculate"}
          </button>
        </div>

        {compData && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-[var(--card-bg)] border-b border-[var(--border-color)] text-xs font-semibold text-[var(--slate)] uppercase tracking-wider">
                Positions on {asOfDate}
              </div>
              <div className="p-0 overflow-x-auto max-h-[300px] overflow-y-auto">
                <table className="w-full text-sm text-left">
                  <thead className="text-[10px] uppercase text-[var(--slate)] bg-[var(--card-bg)] sticky top-0">
                    <tr>
                      <th className="px-4 py-2 font-medium">Ticker</th>
                      <th className="px-4 py-2 font-medium text-right">Shares</th>
                    </tr>
                  </thead>
                  <tbody>
                    {compData.positions?.map((p: any, i: number) => (
                      <tr key={i} className="border-b border-[var(--border-color)] last:border-0 hover:bg-[var(--card-bg)]/50">
                        <td className="px-4 py-2 font-mono text-[var(--brand-blue-light)]">{p.Ticker}</td>
                        <td className="px-4 py-2 text-right text-[var(--foreground)]">{p.Shares?.toFixed(4)}</td>
                      </tr>
                    ))}
                    {!compData.positions?.length && (
                      <tr><td colSpan={2} className="px-4 py-8 text-center text-[var(--slate)]">No positions found on this date.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-[var(--card-bg)] border-b border-[var(--border-color)] text-xs font-semibold text-[var(--slate)] uppercase tracking-wider">
                First Appearance Dates
              </div>
              <div className="p-0 overflow-x-auto max-h-[300px] overflow-y-auto">
                <table className="w-full text-sm text-left">
                  <thead className="text-[10px] uppercase text-[var(--slate)] bg-[var(--card-bg)] sticky top-0">
                    <tr>
                      <th className="px-4 py-2 font-medium">Ticker</th>
                      <th className="px-4 py-2 font-medium text-right">First Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {compData.first_dates?.map((p: any, i: number) => (
                      <tr key={i} className="border-b border-[var(--border-color)] last:border-0 hover:bg-[var(--card-bg)]/50">
                        <td className="px-4 py-2 font-mono text-[var(--brand-blue-light)]">{p.Ticker}</td>
                        <td className="px-4 py-2 text-right text-[var(--foreground)]">{p["First date with position"]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 2. Ledger Search */}
      <section className="space-y-4">
        <h3 className="text-lg font-medium text-[var(--foreground)] border-l-2 border-brand-gold pl-3">Ledger Ticker Search</h3>
        <div className="flex flex-col md:flex-row gap-4 mb-4">
          <div className="flex items-center gap-2 bg-[var(--background)] border border-[var(--border-color)] rounded-md px-3 py-1.5 focus-within:border-brand-gold transition-colors flex-1 max-w-sm">
            <Search className="w-4 h-4 text-[var(--slate)]" />
            <input 
              type="text" 
              placeholder="e.g. SWDA.L"
              value={searchTicker} 
              onChange={(e) => setSearchTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && fetchLedgerRows()}
              className="bg-transparent text-sm text-[var(--foreground)] focus:outline-none w-full font-mono uppercase"
            />
          </div>
          <button 
            onClick={fetchLedgerRows}
            disabled={ledgerLoading || !searchTicker}
            className="bg-[var(--background)] border border-[var(--border-color)] hover:border-brand-gold text-[var(--foreground)] px-4 py-1.5 rounded-md text-sm transition-colors flex items-center gap-2 disabled:opacity-50"
          >
            {ledgerLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : "Search"}
          </button>
        </div>

        {ledgerRows.length > 0 && (
          <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg overflow-hidden">
            <div className="p-0 overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-[10px] uppercase text-[var(--slate)] bg-[var(--card-bg)] sticky top-0">
                  <tr>
                    <th className="px-4 py-2 font-medium">Date</th>
                    <th className="px-4 py-2 font-medium">Action</th>
                    <th className="px-4 py-2 font-medium">Asset Name</th>
                    <th className="px-4 py-2 font-medium text-right">Qty</th>
                    <th className="px-4 py-2 font-medium text-right">Net Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {ledgerRows.map((r: any, i: number) => (
                    <tr key={i} className="border-b border-[var(--border-color)] last:border-0 hover:bg-[var(--card-bg)]/50">
                      <td className="px-4 py-2 text-[var(--slate)]">{r.Date}</td>
                      <td className="px-4 py-2">
                        <span className={`px-2 py-0.5 rounded text-xs ${r.Action === 'Buy' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                          {r.Action}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-[var(--foreground)] truncate max-w-[200px]">{r["Asset Name"]}</td>
                      <td className="px-4 py-2 text-right text-[var(--foreground)]">{r.Qty}</td>
                      <td className="px-4 py-2 text-right text-[var(--foreground)]">{r["Net Amount"]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* 3. Engine Audit */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium text-[var(--foreground)] border-l-2 border-brand-gold pl-3">Last Engine Run Audit</h3>
          <button onClick={fetchAudit} className="text-[var(--slate)] hover:text-brand-gold transition-colors">
            <RefreshCw className={`w-4 h-4 ${auditLoading ? "animate-spin" : ""}`} />
          </button>
        </div>

        {auditError ? (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-sm text-red-300">
            <span className="font-semibold text-red-400">Failed to load audit: </span>{auditError}
          </div>
        ) : auditData?.status === "no_data" ? (
          <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg p-8 text-center text-[var(--slate)] text-sm">
            No audit data found for {account}. Please run a full recalculation.
          </div>
        ) : auditData ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg overflow-hidden p-4">
               <h4 className="text-sm font-semibold text-[var(--foreground)] mb-3">Pricing State</h4>
               <div className="space-y-2 text-sm">
                 <div className="flex justify-between border-b border-[var(--border-color)] pb-1">
                   <span className="text-[var(--slate)]">Expected Prices</span>
                   <span className="font-mono text-brand-gold">{Object.keys(auditData.expected_prices || {}).length} items</span>
                 </div>
                 <div className="flex justify-between border-b border-[var(--border-color)] pb-1">
                   <span className="text-[var(--slate)]">Raw Ledger Rows</span>
                   <span className="font-mono">{auditData.df_raw_for_audit?.length || 0}</span>
                 </div>
                 <div className="flex justify-between border-b border-[var(--border-color)] pb-1">
                   <span className="text-[var(--slate)]">Parsed Ledger Rows</span>
                   <span className="font-mono">{auditData.df_parsed?.length || 0}</span>
                 </div>
                 <div className="flex justify-between border-b border-[var(--border-color)] pb-1">
                   <span className="text-[var(--slate)]">Force Full Prices</span>
                   <span className={`font-mono font-semibold ${auditData._force_full_prices ? "text-amber-400" : "text-[var(--slate)]"}`}>
                     {auditData._force_full_prices ? "YES (Repair)" : "NO (Incremental)"}
                   </span>
                 </div>
                 <div className="flex justify-between pb-1">
                   <span className="text-[var(--slate)]">Full Engine Ran</span>
                   <span className="font-mono text-green-400">Yes</span>
                 </div>
               </div>
            </div>

            <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg overflow-hidden">
              <div className="px-4 py-2 bg-[var(--card-bg)] border-b border-[var(--border-color)] text-xs font-semibold text-[var(--slate)] uppercase tracking-wider">
                Price Multipliers &amp; Sources
              </div>
              <div className="p-0 overflow-x-auto max-h-[200px] overflow-y-auto">
                <table className="w-full text-sm text-left">
                  <thead className="text-[10px] uppercase text-[var(--slate)] bg-[var(--card-bg)] sticky top-0">
                    <tr>
                      <th className="px-4 py-2 font-medium">Ticker</th>
                      <th className="px-4 py-2 font-medium text-right">Multiplier</th>
                      <th className="px-4 py-2 font-medium text-right">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.keys(auditData.multipliers || {}).map((t, i) => (
                      <tr key={i} className="border-b border-[var(--border-color)] last:border-0 hover:bg-[var(--card-bg)]/50">
                        <td className="px-4 py-1.5 font-mono text-[var(--brand-blue-light)]">{t}</td>
                        <td className="px-4 py-1.5 text-right text-[var(--foreground)]">{auditData.multipliers[t]}</td>
                        <td className="px-4 py-1.5 text-right text-[var(--slate)] text-xs">{auditData.sources?.[t] || "stooq"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-[var(--slate)]">Loading audit data...</div>
        )}
      </section>

      {/* 4. Run Logs */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium text-[var(--foreground)] border-l-2 border-brand-gold pl-3">Storage Run Logs</h3>
          <button onClick={fetchLogs} className="text-[var(--slate)] hover:text-brand-gold transition-colors">
            <RefreshCw className={`w-4 h-4 ${logsLoading ? "animate-spin" : ""}`} />
          </button>
        </div>

        <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg overflow-hidden">
          <div className="p-0 overflow-x-auto max-h-[300px] overflow-y-auto">
             <table className="w-full text-sm text-left">
                <thead className="text-[10px] uppercase text-[var(--slate)] bg-[var(--card-bg)] sticky top-0">
                  <tr>
                    <th className="px-4 py-2 font-medium">ID</th>
                    <th className="px-4 py-2 font-medium">Timestamp (UTC)</th>
                    <th className="px-4 py-2 font-medium">Account</th>
                    <th className="px-4 py-2 font-medium">Type</th>
                    <th className="px-4 py-2 font-medium text-right">Rows Written</th>
                  </tr>
                </thead>
                <tbody>
                  {runLogs.map((log: any) => (
                    <tr key={log.id} className="border-b border-[var(--border-color)] last:border-0 hover:bg-[var(--card-bg)]/50">
                      <td className="px-4 py-2 text-[var(--slate)] text-xs">{log.id}</td>
                      <td className="px-4 py-2 font-mono text-[var(--foreground)]">{log.run_timestamp?.replace("T", " ")?.slice(0, 19)}</td>
                      <td className="px-4 py-2 text-[var(--brand-blue-light)]">{log.account}</td>
                      <td className="px-4 py-2 text-[var(--slate)] text-xs uppercase tracking-wider">{log.run_type}</td>
                      <td className="px-4 py-2 text-right text-[var(--foreground)] font-mono">{log.rows_written}</td>
                    </tr>
                  ))}
                  {!runLogs.length && (
                    <tr><td colSpan={5} className="px-4 py-8 text-center text-[var(--slate)]">No run logs recorded yet.</td></tr>
                  )}
                </tbody>
              </table>
          </div>
        </div>
      </section>

      {/* 5. Legacy Cash Adjustment */}
      <section className="space-y-4 pb-8">
        <h3 className="text-lg font-medium text-[var(--foreground)] border-l-2 border-brand-gold pl-3">Adjust Initial Cash Balance</h3>
        <p className="text-xs text-[var(--slate)]">Use this if your 2017 starting balance doesn&apos;t match your historical records. This adjusts the starting line only for {account}.</p>
        
        <div className="flex flex-col md:flex-row items-end gap-4 max-w-md bg-[var(--background)] border border-[var(--border-color)] rounded-lg p-6">
          <div className="flex-1 w-full">
            <label className="block text-[10px] uppercase tracking-wider text-[var(--slate)] font-semibold mb-1">Legacy Cash Adjustment (£)</label>
            <input 
              type="number" step="any"
              value={legacyAdj}
              onChange={(e) => setLegacyAdj(parseFloat(e.target.value) || 0)}
              className="w-full bg-transparent border border-[var(--border-color)] rounded px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-brand-gold"
            />
          </div>
          <button 
            onClick={handleSaveAdj}
            disabled={isSavingAdj}
            className="flex items-center gap-2 bg-brand-gold text-[var(--background)] hover:bg-[#b58b38] px-4 py-2 rounded text-sm font-semibold tracking-wider uppercase transition-colors disabled:opacity-50"
          >
            <Save className="w-4 h-4" /> Save
          </button>
        </div>
      </section>

    </div>
  );
}
