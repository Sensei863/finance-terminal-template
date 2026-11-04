"use client";

import React, { useState, useEffect } from "react";
import { Upload, Trash, AlertTriangle, AlertCircle, RefreshCw, BarChart2, PieChart as PieChartIcon, Activity } from "lucide-react";
import { 
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine
} from "recharts";

interface LookThroughProps {
  account: string;
}

export function LookThroughSection({ account }: LookThroughProps) {
  const [activeTab, setActiveTab] = useState<"registry" | "overlap" | "sector" | "movers">("registry");
  
  // Data States
  const [registry, setRegistry] = useState<any[]>([]);
  const [warnings, setWarnings] = useState<any[]>([]);
  const [analysis, setAnalysis] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  
  // Overlap drilldown state
  const [selectedEtfA, setSelectedEtfA] = useState<string>("");
  const [selectedEtfB, setSelectedEtfB] = useState<string>("");
  const [overlapDetailData, setOverlapDetailData] = useState<any[]>([]);
  const [loadingOverlap, setLoadingOverlap] = useState(false);
  
  // Movers state
  const [moversPeriod, setMoversPeriod] = useState<"1d" | "1w">("1d");

  // Fetch initial data
  useEffect(() => {
    fetchRegistry();
    fetchWarnings();
  }, [account]);

  // Fetch analysis data when account changes
  useEffect(() => {
    fetchAnalysis();
  }, [account]);

  const fetchRegistry = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/lookthrough/registry`);
      const data = await res.json();
      setRegistry(data.registry || []);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchWarnings = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/lookthrough/warnings?account=${encodeURIComponent(account)}`);
      const data = await res.json();
      setWarnings(data.warnings || []);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchAnalysis = async (forceRefresh = false) => {
    setLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/lookthrough/analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account, force_refresh: forceRefresh })
      });
      if (res.ok) {
        const data = await res.json();
        setAnalysis(data);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);
    
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/lookthrough/upload`, {
        method: "POST",
        body: formData,
      });
      const result = await res.json();
      
      if (result.status === "synthetic") {
        alert("Synthetic ETF detected! Please upload an index proxy PDF/CSV instead.");
        return;
      }
      
      let tickerToSave = result.suggested_name;
      const userInput = window.prompt("Please enter the exact ticker symbol for this ETF (e.g., ROBO.L):", result.suggested_name);
      
      if (userInput === null || userInput.trim() === "") {
        setUploading(false);
        return; // User cancelled
      }
      tickerToSave = userInput.trim();

      // Auto-save physical holdings using user-provided ticker
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/lookthrough/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          etf_ticker: tickerToSave,
          provider: result.provider,
          df_records: result.data,
          is_synthetic: false
        })
      });
      
      fetchRegistry();
      fetchAnalysis(true);
    } catch (err) {
      console.error(err);
      alert("Error uploading file.");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (ticker: string) => {
    if (!confirm(`Delete holdings for ${ticker}?`)) return;
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/lookthrough/holdings/${ticker}`, { method: "DELETE" });
      fetchRegistry();
      fetchAnalysis(true);
    } catch (e) {
      console.error(e);
    }
  };

  const handleIgnore = async (ticker: string, currentVal: boolean) => {
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/lookthrough/ignore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ etf_ticker: ticker, ignore: !currentVal })
      });
      fetchRegistry();
      fetchAnalysis(true);
    } catch (e) {
      console.error(e);
    }
  };

  // UI Helpers
  const formatPct = (val: number | null) => val != null ? `${val.toFixed(2)}%` : "—";
  const formatCurrency = (val: number | null) => val != null ? `${analysis?.currency_symbol || '£'}${val.toLocaleString(undefined, {maximumFractionDigits: 0})}` : "—";

  const getHeatmapColor = (val: number) => {
    // 0 -> Green (Hue 120), 0.5 -> Yellow (Hue 60), 1.0 -> Red (Hue 0)
    const h = (1 - val) * 120;
    return `hsla(${h}, 70%, 40%, 0.6)`;
  };

  const fetchOverlapPair = async (a: string, b: string) => {
    if (!a || !b) return;
    setLoadingOverlap(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/lookthrough/overlap-pair`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account, etf_a: a, etf_b: b })
      });
      if (res.ok) {
        const data = await res.json();
        setOverlapDetailData(data.data || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingOverlap(false);
    }
  };

  useEffect(() => {
    if (selectedEtfA && selectedEtfB) {
      fetchOverlapPair(selectedEtfA, selectedEtfB);
    } else {
      setOverlapDetailData([]);
    }
  }, [selectedEtfA, selectedEtfB]);

  const COLORS = ['#8b7355', '#334155', '#64748b', '#94a3b8', '#cbd5e1', '#0f172a'];

  const renderMessage = (text: string) => {
    return text.split(/(\*\*.*?\*\*)/).map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i} className="font-bold">{part.slice(2, -2)}</strong>;
      }
      return <span key={i}>{part}</span>;
    });
  };

  const getDisplayName = (t: string) => {
    const regItem = registry.find(r => r.etf_ticker === t);
    if (!regItem) return t;
    if (regItem.full_name) return `${regItem.full_name} (${t})`;
    if (regItem.index_proxy_note) return `${regItem.index_proxy_note} (${t})`;
    if (regItem.provider) {
      const p = regItem.provider.charAt(0).toUpperCase() + regItem.provider.slice(1);
      return `${p} (${t})`;
    }
    return t;
  };

  return (
    <div className="space-y-6 pt-12">
      
      {/* Warnings Banner */}
      {warnings.length > 0 && (
        <div className="space-y-2 mt-6">
          {warnings.map((w, i) => (
            <div key={i} className={`p-3 text-xs border rounded flex items-center gap-2 ${
              w.type === "STALE" ? "bg-yellow-500/10 border-yellow-500/20 text-yellow-600" : "bg-brand-red/10 border-brand-red/20 text-brand-red"
            }`}>
              {w.type === "STALE" ? <AlertTriangle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
              <span>{renderMessage(w.message)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-4 border-b border-[var(--border-color)]">
        {[
          { id: "registry", label: "Holdings Registry" },
          { id: "overlap", label: "Overlap" },
          { id: "sector", label: "Sector & Geo" },
          { id: "movers", label: "Top Movers" }
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id as any)}
            className={`pb-2 px-2 text-sm font-semibold transition-colors ${
              activeTab === t.id 
                ? "border-b-2 border-brand-gold text-brand-gold" 
                : "border-b-2 border-transparent text-brand-slate hover:text-[var(--foreground)]"
            }`}
          >
            {t.label}
          </button>
        ))}
        </div>

      {/* ── SECTION: REGISTRY ── */}
      {activeTab === "registry" && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="font-serif text-xl text-[var(--foreground)]">Holdings Registry</h3>
            <label className="flex items-center justify-center gap-2 px-4 py-2 bg-brand-navy hover:bg-brand-navy-light text-brand-cream text-xs font-semibold tracking-wide uppercase cursor-pointer rounded transition-colors">
              <Upload className="w-4 h-4" />
              {uploading ? "Uploading..." : "Upload Holdings"}
              <input type="file" className="hidden" accept=".csv,.xls,.xlsx" onChange={handleFileUpload} disabled={uploading} />
            </label>
          </div>

          <div className="border border-[var(--border-color)] overflow-hidden bg-[var(--background)]">
            <table className="w-full text-sm text-left">
              <thead>
                <tr className="bg-[var(--navy)] text-brand-slate text-[9px] uppercase tracking-widest border-b border-[var(--border-color)]">
                  <th className="py-2 px-4 font-semibold">ETF Ticker</th>
                  <th className="py-2 px-4 font-semibold">Provider</th>
                  <th className="py-2 px-4 font-semibold">Upload Date</th>
                  <th className="py-2 px-4 font-semibold">Status</th>
                  <th className="py-2 px-4 font-semibold text-center">Ignore</th>
                  <th className="py-2 px-4 font-semibold text-center">Actions</th>
                </tr>
              </thead>
              <tbody className="text-[var(--foreground)]">
                {registry.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-4 text-center text-brand-slate text-xs italic">No holdings uploaded yet.</td>
                  </tr>
                ) : registry.map((row, i) => (
                  <tr key={i} className="border-b border-[var(--border-color)] hover:bg-[var(--border-color)]/20 transition-colors">
                    <td className="py-2 px-4 font-serif font-semibold">{row.etf_ticker}</td>
                    <td className="py-2 px-4">{row.provider}</td>
                    <td className="py-2 px-4 font-mono text-xs">{row.last_upload}</td>
                    <td className="py-2 px-4 text-xs">{row.Status}</td>
                    <td className="py-2 px-4 text-center">
                      <input 
                        type="checkbox" 
                        checked={row.ignore_look_through === 1}
                        onChange={() => handleIgnore(row.etf_ticker, row.ignore_look_through === 1)}
                        className="accent-brand-gold cursor-pointer"
                      />
                    </td>
                    <td className="py-2 px-4 text-center">
                      <button onClick={() => handleDelete(row.etf_ticker)} className="text-brand-red hover:text-brand-red/80">
                        <Trash className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── SECTION: OVERLAP ── */}
      {activeTab === "overlap" && (
        <div className="space-y-6">
          <h3 className="font-serif text-xl text-[var(--foreground)]">ETF Overlap Analysis</h3>
          
          {analysis?.overlap_matrix?.labels ? (
            <div className="p-4 border border-[var(--border-color)] overflow-x-auto">
              <table className="text-xs font-mono text-center">
                <thead>
                  <tr>
                    <th className="p-2"></th>
                    {analysis.overlap_matrix.labels.map((l: string) => <th key={l} className="p-2 font-semibold text-brand-slate">{l}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {analysis.overlap_matrix.values.map((row: number[], i: number) => (
                    <tr key={i}>
                      <td className="p-2 font-semibold text-brand-slate text-left">{analysis.overlap_matrix.labels[i]}</td>
                      {row.map((val: number, j: number) => {
                        const hasOverlap = val > 0;
                        return (
                          <td 
                            key={j} 
                            className={`p-2 border border-[var(--border-color)]/30 ${hasOverlap ? 'font-bold text-white' : ''}`}
                            style={{ backgroundColor: hasOverlap ? getHeatmapColor(val) : undefined }}
                          >
                            {val.toFixed(2)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-4 border border-[var(--border-color)] text-sm text-brand-slate">
              Upload at least 2 ETFs to see overlap matrix.
            </div>
          )}

          <div className="space-y-4">
            <h4 className="text-[10px] uppercase tracking-[0.2em] text-brand-slate font-semibold flex items-center justify-between">
              <span>Shared Constituents Detail</span>
            </h4>
            
            <div className="flex gap-4 items-center">
              <div className="flex-1">
                <label className="block text-[10px] uppercase text-brand-slate mb-1">ETF A</label>
                <select 
                  className="w-full p-2 bg-[#0f172a] border border-[var(--border-color)] text-sm rounded text-white"
                  value={selectedEtfA}
                  onChange={(e) => setSelectedEtfA(e.target.value)}
                >
                  <option value="">-- Select ETF --</option>
                  {(analysis?.overlap_matrix?.labels || []).map((t: string) => {
                    const displayName = getDisplayName(t);
                    // If selected, show just ticker, else show display name. 
                    // Native selects display the text content of the selected option, so we just set the text content dynamically based on selection state.
                    return <option key={t} value={t}>{selectedEtfA === t ? t : displayName}</option>;
                  })}
                </select>
              </div>
              <div className="flex-1">
                <label className="block text-[10px] uppercase text-brand-slate mb-1">ETF B</label>
                <select 
                  className="w-full p-2 bg-[#0f172a] border border-[var(--border-color)] text-sm rounded text-white"
                  value={selectedEtfB}
                  onChange={(e) => setSelectedEtfB(e.target.value)}
                >
                  <option value="">-- Select ETF --</option>
                  {(analysis?.overlap_matrix?.labels || []).map((t: string) => {
                    const displayName = getDisplayName(t);
                    return <option key={t} value={t}>{selectedEtfB === t ? t : displayName}</option>;
                  })}
                </select>
              </div>
            </div>

            {loadingOverlap ? (
              <div className="text-sm text-brand-slate">Loading overlap details...</div>
            ) : selectedEtfA && selectedEtfB ? (
              overlapDetailData.length > 0 ? (
                <div className="border border-[var(--border-color)] overflow-hidden max-h-[400px] overflow-y-auto mt-4">
                  <table className="w-full text-sm text-left">
                    <thead className="sticky top-0 bg-[var(--navy)] text-brand-slate text-[9px] uppercase tracking-widest border-b border-[var(--border-color)]">
                      <tr>
                        <th className="py-2 px-4">ETF A</th>
                        <th className="py-2 px-4">ETF B</th>
                        <th className="py-2 px-4">Constituent</th>
                        <th className="py-2 px-4">Min Weight</th>
                      </tr>
                    </thead>
                    <tbody className="text-[var(--foreground)]">
                      {overlapDetailData.map((r: any, i: number) => (
                        <tr key={i} className="border-b border-[var(--border-color)]/30">
                          <td className="py-2 px-4 font-mono text-xs">{r["ETF A"]}</td>
                          <td className="py-2 px-4 font-mono text-xs">{r["ETF B"]}</td>
                          <td className="py-2 px-4">{r["Constituent"]}</td>
                          <td className="py-2 px-4 font-mono text-xs">{formatPct(r["Min Weight (overlap)"] || r["Min Weight (%)"])}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="p-4 border border-[var(--border-color)] text-sm text-brand-slate mt-4">
                  No overlap found between {selectedEtfA} and {selectedEtfB}.
                </div>
              )
            ) : null}
          </div>
        </div>
      )}

      {/* ── SECTION: SECTOR & GEO ── */}
      {activeTab === "sector" && (
        <div className="space-y-8">
          <div className="grid grid-cols-2 gap-8">
            <div className="space-y-4">
              <h3 className="font-serif text-lg text-[var(--foreground)]">Sector Breakdown</h3>
              <div className="h-[300px] border border-[var(--border-color)] p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={analysis?.df_sector || []} dataKey="portfolio_weight_pct" nameKey="sector" cx="50%" cy="50%" outerRadius={100} innerRadius={60} label={({name, percent}) => `${name} ${((percent || 0) * 100).toFixed(1)}%`}>
                      {(analysis?.df_sector || []).map((entry: any, index: number) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(val: any) => formatPct(val)} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="space-y-4">
              <h3 className="font-serif text-lg text-[var(--foreground)]">Geography</h3>
              <div className="h-[300px] border border-[var(--border-color)] p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={analysis?.df_geography?.slice(0, 15) || []} layout="vertical" margin={{ left: 50 }}>
                    <XAxis type="number" hide />
                    <YAxis dataKey="country" type="category" axisLine={false} tickLine={false} style={{ fontSize: '10px' }} width={80} interval={0} />
                    <Tooltip formatter={(val: any) => formatPct(val)} />
                    <Bar dataKey="portfolio_weight_pct" fill="#8b7355" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <h4 className="text-[10px] uppercase tracking-[0.2em] text-brand-slate font-semibold">Top 30 Consolidated Holdings</h4>
            <div className="border border-[var(--border-color)] overflow-hidden">
              <table className="w-full text-sm text-right">
                <thead className="bg-[var(--navy)] text-brand-slate text-[9px] uppercase tracking-widest border-b border-[var(--border-color)]">
                  <tr>
                    <th className="py-2 px-4 text-left">Name</th>
                    <th className="py-2 px-4">Sector</th>
                    <th className="py-2 px-4">Country</th>
                    <th className="py-2 px-4">Weight</th>
                    <th className="py-2 px-4">Effective Value</th>
                  </tr>
                </thead>
                <tbody className="text-[var(--foreground)]">
                  {(analysis?.df_top_holdings || []).map((r: any, i: number) => (
                    <tr key={i} className="border-b border-[var(--border-color)]/50 hover:bg-[var(--border-color)]/20">
                      <td className="py-2 px-4 text-left font-serif">{r.constituent_name}</td>
                      <td className="py-2 px-4 text-xs">{r.sector}</td>
                      <td className="py-2 px-4 text-xs">{r.country}</td>
                      <td className="py-2 px-4 font-mono text-xs">{formatPct(r.portfolio_weight_pct)}</td>
                      <td className="py-2 px-4 font-mono text-xs">{formatCurrency(r.effective_value_gbp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── SECTION: MOVERS ── */}
      {activeTab === "movers" && (
        <div className="space-y-6">
          <div className="flex items-center justify-between border-b border-[var(--border-color)] pb-2">
            <h3 className="font-serif text-xl text-[var(--foreground)]">P&L Attribution — Top Movers</h3>
            <div className="flex gap-2">
              <button 
                onClick={() => setMoversPeriod("1d")} 
                className={`text-xs px-3 py-1 border rounded ${moversPeriod === "1d" ? "bg-brand-gold text-white border-brand-gold" : "border-[var(--border-color)]"}`}
              >1 Day</button>
              <button 
                onClick={() => setMoversPeriod("1w")} 
                className={`text-xs px-3 py-1 border rounded ${moversPeriod === "1w" ? "bg-brand-gold text-white border-brand-gold" : "border-[var(--border-color)]"}`}
              >1 Week</button>
            </div>
          </div>

          <div className="h-[400px] border border-[var(--border-color)] p-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={(moversPeriod === "1d" ? analysis?.df_movers_1d : analysis?.df_movers_1w)?.slice(0, 20) || []}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-color)" />
                <XAxis dataKey="Constituent" tick={{ fontSize: 10 }} interval={0} angle={-45} textAnchor="end" height={80} />
                <YAxis tickFormatter={(val) => `${analysis?.currency_symbol || '£'}${val}`} tick={{ fontSize: 10 }} />
                <Tooltip formatter={(val: any) => formatCurrency(val)} />
                <ReferenceLine y={0} stroke="#000" />
                <Bar dataKey="P&L Contribution (Local)">
                  {((moversPeriod === "1d" ? analysis?.df_movers_1d : analysis?.df_movers_1w)?.slice(0, 20) || []).map((entry: any, index: number) => (
                    <Cell key={`cell-${index}`} fill={entry["P&L Contribution (Local)"] >= 0 ? "#22c55e" : "#ef4444"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="border border-[var(--border-color)] overflow-hidden max-h-[400px] overflow-y-auto">
            <table className="w-full text-sm text-right">
              <thead className="sticky top-0 bg-[var(--navy)] text-brand-slate text-[9px] uppercase tracking-widest border-b border-[var(--border-color)]">
                <tr>
                  <th className="py-2 px-4 text-left">Constituent</th>
                  <th className="py-2 px-4">Held Via</th>
                  <th className="py-2 px-4">Effective Value</th>
                  <th className="py-2 px-4">Price Return</th>
                  <th className="py-2 px-4">Contribution</th>
                </tr>
              </thead>
              <tbody className="text-[var(--foreground)]">
                {((moversPeriod === "1d" ? analysis?.df_movers_1d : analysis?.df_movers_1w) || []).map((r: any, i: number) => (
                  <tr key={i} className="border-b border-[var(--border-color)]/30">
                    <td className="py-2 px-4 text-left font-serif">{r.Constituent}</td>
                    <td className="py-2 px-4 font-mono text-xs">{r["Held via"]}</td>
                    <td className="py-2 px-4 font-mono text-xs">{formatCurrency(r["Effective Value (Local)"])}</td>
                    <td className={`py-2 px-4 font-mono text-xs ${r["Price Return (%)"] >= 0 ? "text-brand-green" : "text-brand-red"}`}>{formatPct(r["Price Return (%)"])}</td>
                    <td className={`py-2 px-4 font-mono text-xs font-bold ${r["P&L Contribution (Local)"] >= 0 ? "text-brand-green" : "text-brand-red"}`}>{formatCurrency(r["P&L Contribution (Local)"])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
