"use client";

import React, { useState, useEffect, Suspense } from "react";
import { RefreshCw, Search, ChevronDown, ChevronRight, Plus, Trash, Database, Clock, Settings, Zap, Activity } from "lucide-react";
import { PortfolioDashboard } from "@/components/portfolio/PortfolioDashboard";
import { TradeIngestion } from "@/components/portfolio/TradeIngestion";
import { LookThroughSection } from "@/components/portfolio/LookThroughSection";
import { PortfolioOptimization } from "@/components/portfolio/PortfolioOptimization";
import { FactorAnalysis } from "@/components/portfolio/FactorAnalysis";
import { PerformanceAnalysis } from "@/components/portfolio/PerformanceAnalysis";
import { useSearchParams } from "next/navigation";
import { useIsMobile } from "@/hooks/useIsMobile";
import { MonitorOff } from "lucide-react";
import { Account, SyntheticBenchmark, StorageRunLogEntry, AutoRefreshConfig } from "@/types";

function PortfolioContent() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const searchParams = useSearchParams();
  const queryMode = searchParams.get("mode") as "dashboard" | "ingestion" | "lookthrough" | "optimization" | "factors" | "performance" | null;
  const mode = queryMode === "ingestion" ? "ingestion" : 
               queryMode === "lookthrough" ? "lookthrough" : 
               queryMode === "optimization" ? "optimization" : 
               queryMode === "factors" ? "factors" : 
               queryMode === "performance" ? "performance" : "dashboard";

  const isMobile = useIsMobile();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string>("Consolidated");
  
  // Update sidebar default based on mobile
  useEffect(() => {
    setSidebarOpen(!isMobile);
  }, [isMobile]);

  useEffect(() => {
    const savedAccount = localStorage.getItem("selectedAccount");
    if (savedAccount) setSelectedAccount(savedAccount);
  }, []);

  const handleSelectAccount = (val: string) => {
    setSelectedAccount(val);
    localStorage.setItem("selectedAccount", val);
  };
  
  // --- New Sidebar States ---
  const [viewMode, setViewMode] = useState<"Wealth Management" | "Third Party" | "Playground">("Wealth Management");
  const [syntheticBenchmarks, setSyntheticBenchmarks] = useState<SyntheticBenchmark[]>([]);
  const [selectedSynthetic, setSelectedSynthetic] = useState<string>("None (use index line only)");
  const [isSyntheticMissing, setIsSyntheticMissing] = useState(false);

  useEffect(() => {
    const savedBm = localStorage.getItem("selectedSynthetic");
    if (savedBm) setSelectedSynthetic(savedBm);
    const savedAccount = localStorage.getItem("selectedAccount");
    if (savedAccount) setSelectedAccount(savedAccount);
  }, []);

  const handleSetSynthetic = (val: string) => {
    setSelectedSynthetic(val);
    localStorage.setItem("selectedSynthetic", val);
  };
  
  // Expanders
  const [expanderManage, setExpanderManage] = useState(false);
  const [expanderData, setExpanderData] = useState(false);
  const [expanderAuto, setExpanderAuto] = useState(false);

  // Engine Actions
  const [runAllAccounts, setRunAllAccounts] = useState(false);
  const [repairPrices, setRepairPrices] = useState(false);
  const [isRecalculating, setIsRecalculating] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);
  const [isFlushing, setIsFlushing] = useState(false);
  const [isRefreshingAnalysis, setIsRefreshingAnalysis] = useState(false);
  const [isFixingUnknown, setIsFixingUnknown] = useState(false);

  // Manage Accounts Form
  const [newAcctName, setNewAcctName] = useState("");
  const [newAcctClass, setNewAcctClass] = useState("Live");
  const [newAcctCcy, setNewAcctCcy] = useState("GBP");
  const [acctToDelete, setAcctToDelete] = useState("");

  // Data Maintenance
  const [runLogs, setRunLogs] = useState<StorageRunLogEntry[]>([]);

  // Auto Refresh
  const [arEnabled, setArEnabled] = useState(false);
  const [arTime, setArTime] = useState("01:00");
  const [arStatus, setArStatus] = useState<Partial<AutoRefreshConfig>>({});
  const [refreshKey, setRefreshKey] = useState(0);

  // --- Initial Data Load ---
  useEffect(() => {
    // 1. Load Accounts
    fetch(`${API_URL}/api/ingestion/accounts`)
      .then(res => res.json())
      .then(d => {
        if (d.accounts) {
          const formatted = d.accounts.map((a: any) => 
            typeof a === "string" ? { name: a, classification: "Live" } : a
          );
          if (!formatted.some((a: any) => a.name === "Consolidated")) {
             formatted.unshift({ name: "Consolidated", classification: "Live" });
          }
          setAccounts(formatted);
          if (!selectedAccount) handleSelectAccount("Consolidated");
          if (!acctToDelete && formatted.length > 1) {
            setAcctToDelete(formatted.filter((a: any) => a.name !== "Consolidated")[0]?.name || "");
          }
        }
      })
      .catch(e => console.error(e));

    // 2. Load Benchmarks
    fetch(`${API_URL}/api/system/benchmarks`)
      .then(res => res.json())
      .then(d => setSyntheticBenchmarks(d.benchmarks || []))
      .catch(e => console.error(e));

    // 3. Load Logs
    fetch(`${API_URL}/api/system/logs`)
      .then(res => res.json())
      .then(d => setRunLogs(d.logs || []))
      .catch(e => console.error(e));

    // 4. Load Auto-refresh Config
    fetch(`${API_URL}/api/system/schedule`)
      .then(res => res.json())
      .then(d => {
        setArEnabled(!!d.auto_refresh_enabled);
        setArTime(`${String(d.auto_refresh_hour || 1).padStart(2, '0')}:${String(d.auto_refresh_minute || 0).padStart(2, '0')}`);
        setArStatus(d);
      })
      .catch(e => console.error(e));
  }, [refreshKey]);

  // --- API Handlers ---
  const handleRecalculate = async () => {
    if (!selectedAccount && !runAllAccounts) return;
    setIsRecalculating(true);
    try {
      const accountsToRun = runAllAccounts 
        ? accounts.map(a => a.name) // Run literally all accounts + Consolidated
        : [selectedAccount];
        
      for (const acct of accountsToRun) {
        const res = await fetch(`${API_URL}/api/portfolio/recalculate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ 
            account: acct, 
            force_full_prices: repairPrices,
            active_bm_name: selectedSynthetic !== "None (use index line only)" ? selectedSynthetic : null
          })
        });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || `Failed to recalculate ${acct}`);
        }
      }
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      console.error(e);
      alert(`Error during recalculation: ${e.message}`);
    } finally {
      setIsRecalculating(false);
    }
  };

  const handleSimulateBenchmark = async () => {
    if (selectedSynthetic === "None (use index line only)") return;
    setIsSimulating(true);
    try {
      await fetch(`${API_URL}/api/portfolio/recalculate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account: selectedAccount, force_full_prices: false, active_bm_name: selectedSynthetic })
      });
      setRefreshKey(k => k + 1);
    } catch (e) {
      console.error(e);
    } finally {
      setIsSimulating(false);
    }
  };

  const handleCreateAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newAcctName.trim()) return;
    try {
      await fetch(`${API_URL}/api/accounts/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_name: newAcctName, classification: newAcctClass, base_currency: newAcctCcy })
      });
      setNewAcctName("");
      setRefreshKey(k => k + 1);
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteAccount = async () => {
    if (!acctToDelete || acctToDelete === "Consolidated") return;
    try {
      await fetch(`${API_URL}/api/accounts/${acctToDelete}`, { method: "DELETE" });
      setRefreshKey(k => k + 1);
    } catch (err) {
      console.error(err);
    }
  };

  const handleFlushCache = async () => {
    setIsFlushing(true);
    try {
      await fetch(`${API_URL}/api/cache/flush`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_view: selectedAccount, force_full_prices: false })
      });
      setRefreshKey(k => k + 1);
    } catch (err) {
      console.error(err);
    } finally {
      setIsFlushing(false);
    }
  };

  const handleSaveSchedule = async () => {
    const [h, m] = arTime.split(":");
    try {
      await fetch(`${API_URL}/api/system/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: arEnabled, hour: parseInt(h, 10), minute: parseInt(m, 10) })
      });
      setRefreshKey(k => k + 1);
    } catch (err) {
      console.error(err);
    }
  };

  // --- Filtering Account Dropdown ---
  const liveOpts = accounts.filter(a => a.classification === "Live").map(a => a.name);
  const thirdPartyOpts = accounts.filter(a => a.classification === "Third Party EUR").map(a => a.name);
  const sandboxOpts = accounts.filter(a => a.classification === "Sandbox").map(a => a.name);

  let activeOptions: string[] = [];
  if (viewMode === "Wealth Management") activeOptions = ["Consolidated", ...liveOpts.filter(a => a !== "Consolidated")];
  else if (viewMode === "Third Party") activeOptions = thirdPartyOpts;
  else if (viewMode === "Playground") activeOptions = sandboxOpts;

  // Auto-select if current mode's options don't contain selected account
  useEffect(() => {
    if (activeOptions.length > 0 && !activeOptions.includes(selectedAccount)) {
      handleSelectAccount(activeOptions[0]);
    }
  }, [viewMode, activeOptions, selectedAccount]);

  // Redirect away from Consolidated in Trade Ingestion tab
  useEffect(() => {
    if (mode === "ingestion" && selectedAccount === "Consolidated") {
      const firstReal = activeOptions.find(opt => opt !== "Consolidated");
      if (firstReal) {
        handleSelectAccount(firstReal);
      }
    }
  }, [mode, selectedAccount, activeOptions]);

  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);

  const fetchLastRefreshed = async () => {
    try {
      const res = await fetch(`${API_URL}/api/lookthrough/status?account=${encodeURIComponent(selectedAccount)}`);
      if (res.ok) {
        const data = await res.json();
        setLastRefreshed(data.computed_at || null);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (selectedAccount) {
      fetchLastRefreshed();
    }
  }, [selectedAccount, refreshKey]);

  const formatLastRefreshed = (isoString: string | null) => {
    if (!isoString) return "Never";
    try {
      const d = new Date(isoString);
      return d.toLocaleString("en-GB", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      });
    } catch (e) {
      return "Unknown";
    }
  };

  return (
    <div className="flex flex-1 h-[calc(100vh-64px)] w-full overflow-hidden bg-[var(--background)] relative">
      {/* Mobile Backdrop */}
      {sidebarOpen && isMobile && (
        <div 
          className="md:hidden fixed inset-0 bg-black/50 backdrop-blur-sm z-40 transition-opacity"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ══ COMMAND SIDEBAR ══ */}
      <aside 
        className={`border-r border-[var(--border-color)] bg-[var(--background)] flex flex-col shrink-0 overflow-y-auto transition-all duration-300 ease-in-out
          fixed md:static inset-y-0 left-0 z-50 md:z-auto h-full
          ${sidebarOpen ? "w-[260px] translate-x-0" : "w-0 -translate-x-full border-transparent"}
        `}
      >
        <div className="p-4 border-b border-[var(--border-color)] bg-[var(--border-color)]/30 flex justify-between items-center">
          <h2 className="text-[10px] uppercase tracking-[0.2em] text-[var(--foreground)] font-semibold flex items-center gap-2">
            <Settings className="w-3 h-3 shrink-0" /> Portfolio Settings
          </h2>
          {isMobile && (
            <button onClick={() => setSidebarOpen(false)} className="text-[var(--foreground)]/70">
              ✕
            </button>
          )}
        </div>
        
        <div className="p-4 space-y-6">
          {/* Account Selection */}
          <div className="space-y-4">
            <h3 className="text-[13px] font-bold uppercase tracking-wider text-brand-gold border-b border-[var(--border-color)] pb-1 mb-4 flex items-center gap-2">
              <Database className="w-4 h-4" /> Account Selection
            </h3>
            
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-xs text-brand-slate hover:text-[var(--foreground)] cursor-pointer">
                <input type="radio" name="viewMode" checked={viewMode === "Wealth Management"} onChange={() => setViewMode("Wealth Management")} className="accent-brand-gold" />
                Wealth Management
              </label>
              <label className="flex items-center gap-2 text-xs text-brand-slate hover:text-[var(--foreground)] cursor-pointer">
                <input type="radio" name="viewMode" checked={viewMode === "Third Party"} onChange={() => setViewMode("Third Party")} className="accent-brand-gold" />
                Third Party
              </label>
              <label className="flex items-center gap-2 text-xs text-brand-slate hover:text-[var(--foreground)] cursor-pointer">
                <input type="radio" name="viewMode" checked={viewMode === "Playground"} onChange={() => setViewMode("Playground")} className="accent-brand-gold" />
                Playground
              </label>
            </div>

            {viewMode === "Wealth Management" && (
              <label className="flex items-center gap-2 text-xs text-brand-slate opacity-70">
                <input type="checkbox" checked readOnly className="accent-brand-gold" /> Live Capital (Consolidated)
              </label>
            )}

            <div className="pt-2">
              <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider mb-2">
                Select {viewMode === "Wealth Management" ? "Live" : viewMode === "Third Party" ? "External" : "Sandbox"} Account
              </label>
              <select 
                value={selectedAccount}
                onChange={e => handleSelectAccount(e.target.value)}
                className="w-full bg-[var(--background)] border border-[var(--border-color)] rounded p-1.5 text-sm outline-none"
              >
                {activeOptions.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          </div>

          {/* Synthetic Benchmark */}
          <div className="space-y-2">
            <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider mb-2">Synthetic Benchmark</label>
            <select
              value={selectedSynthetic}
              onChange={e => handleSetSynthetic(e.target.value)}
              className="w-full bg-[var(--background)] border border-[var(--border-color)] rounded p-1.5 text-sm outline-none"
            >
              <option value="None (use index line only)">None (use index line only)</option>
              {syntheticBenchmarks.map(b => (
                <option key={b.name} value={b.name}>{b.name}</option>
              ))}
            </select>
            
            {selectedSynthetic !== "None (use index line only)" && (
              <div className="mt-2 bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 text-xs p-2 rounded flex flex-col gap-2">
                <div className="flex items-center gap-1 font-semibold">
                  <Zap className="w-3 h-3" /> Selected: {selectedSynthetic}
                </div>
                {isSyntheticMissing && (
                  <button
                    onClick={handleSimulateBenchmark}
                    disabled={isSimulating}
                    className="w-full py-1 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-500 rounded text-xs transition-colors"
                  >
                    {isSimulating ? "Simulating..." : "⚡ Simulate Benchmark"}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Look-Through Controls */}
          {mode === "lookthrough" && (
            <div className="space-y-4 border-t border-[var(--border-color)] pt-4 mt-4">
              <h3 className="text-[13px] font-bold uppercase tracking-wider text-brand-gold pb-1 flex items-center gap-2">
                <Search className="w-4 h-4" /> Look-Through
              </h3>
              
              <div className="text-[10px] text-brand-slate">
                Last Refreshed: <span className="text-[var(--foreground)] font-semibold">{formatLastRefreshed(lastRefreshed)}</span>
              </div>
              
              <button
                onClick={async () => {
                  setIsRefreshingAnalysis(true);
                  try {
                    await fetch(`${API_URL}/api/lookthrough/analysis`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ account: selectedAccount, force_refresh: true })
                    });
                    setRefreshKey(k => k + 1);
                  } catch (e) {
                    console.error(e);
                  } finally {
                    setIsRefreshingAnalysis(false);
                  }
                }}
                disabled={isRefreshingAnalysis || isFixingUnknown}
                className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-[var(--background)] border border-[var(--border-color)] hover:border-brand-gold text-[var(--foreground)] text-xs rounded transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`w-3 h-3 ${isRefreshingAnalysis ? "animate-spin" : ""}`} /> 
                {isRefreshingAnalysis ? "Refreshing..." : "Refresh Analysis"}
              </button>

              <button
                onClick={async () => {
                  setIsFixingUnknown(true);
                  try {
                    const fixRes = await fetch(`${API_URL}/api/lookthrough/fix-unknown`, { method: "POST" });
                    const fixData = await fixRes.json();
                    const results = fixData.results || {};
                    alert(`Unknown metadata repair complete!\n\n- yfinance Fixed: ${results.yf_fixed || 0}\n- Gemini Fixed: ${results.gemini_fixed || 0}\n- Still Unknown: ${results.still_unknown || 0}\n\nRefreshing analysis to apply changes...`);
                    await fetch(`${API_URL}/api/lookthrough/analysis`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ account: selectedAccount, force_refresh: true })
                    });
                    setRefreshKey(k => k + 1);
                  } catch (e) {
                    console.error(e);
                  } finally {
                    setIsFixingUnknown(false);
                  }
                }}
                disabled={isRefreshingAnalysis || isFixingUnknown}
                className="w-full flex flex-col items-center justify-center gap-1 py-2 px-4 bg-[var(--background)] border border-[var(--border-color)] hover:border-brand-gold text-[var(--foreground)] text-xs rounded transition-colors disabled:opacity-50"
              >
                <div className="flex items-center gap-2 text-brand-gold">
                  <Activity className={`w-3 h-3 ${isFixingUnknown ? "animate-pulse" : ""}`} /> 
                  {isFixingUnknown ? "Fixing..." : "Fix Unknown"}
                </div>
                <span className="text-[10px] opacity-70">Sectors/Countries</span>
              </button>
            </div>
          )}

          {/* Manage Accounts Expander */}
          <div className="border border-[var(--border-color)] rounded overflow-hidden">
            <button 
              onClick={() => setExpanderManage(!expanderManage)}
              className="w-full flex items-center justify-between p-2 bg-[var(--border-color)]/20 hover:bg-[var(--border-color)]/40 text-xs font-semibold text-brand-slate transition-colors"
            >
              Manage Accounts {expanderManage ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            </button>
            {expanderManage && (
              <div className="p-3 space-y-4 bg-[var(--background)] text-xs">
                <form onSubmit={handleCreateAccount} className="space-y-2">
                  <p className="font-semibold text-brand-gold">Create New Portfolio</p>
                  <input type="text" placeholder="Account Name" value={newAcctName} onChange={e => setNewAcctName(e.target.value)} className="w-full p-1 border border-[var(--border-color)] bg-[var(--background)] rounded" required />
                  <select value={newAcctClass} onChange={e => setNewAcctClass(e.target.value)} className="w-full p-1 border border-[var(--border-color)] bg-[var(--background)] rounded">
                    <option value="Live">Live</option>
                    <option value="Sandbox">Sandbox</option>
                    <option value="Third Party EUR">Third Party EUR</option>
                  </select>
                  <select value={newAcctCcy} onChange={e => setNewAcctCcy(e.target.value)} className="w-full p-1 border border-[var(--border-color)] bg-[var(--background)] rounded">
                    <option value="GBP">GBP</option>
                    <option value="EUR">EUR</option>
                    <option value="USD">USD</option>
                  </select>
                  <button type="submit" className="w-full p-1.5 bg-brand-navy hover:bg-brand-navy-light text-white rounded flex items-center justify-center gap-1"><Plus className="w-3 h-3" /> Create</button>
                </form>
                
                <div className="space-y-2 pt-2 border-t border-[var(--border-color)]">
                  <p className="font-semibold text-brand-gold">Delete Portfolio</p>
                  <select value={acctToDelete} onChange={e => setAcctToDelete(e.target.value)} className="w-full p-1 border border-[var(--border-color)] bg-[var(--background)] rounded">
                    {accounts.filter(a => a.name !== "Consolidated").map(a => <option key={a.name} value={a.name}>{a.name}</option>)}
                  </select>
                  <button onClick={handleDeleteAccount} className="w-full p-1.5 bg-brand-red/20 hover:bg-brand-red/40 text-brand-red border border-brand-red/30 rounded flex items-center justify-center gap-1"><Trash className="w-3 h-3" /> Delete</button>
                </div>
              </div>
            )}
          </div>

          <hr className="border-[var(--border-color)]" />

          {/* Portfolio Engine */}
          <div className="space-y-3">
            <h3 className="text-[13px] font-bold uppercase tracking-wider text-brand-gold border-b border-[var(--border-color)] pb-1 mb-4 flex items-center gap-2">
              <RefreshCw className="w-4 h-4" /> Portfolio Engine
            </h3>
            
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-xs text-brand-slate hover:text-[var(--foreground)] cursor-pointer">
                <input type="checkbox" checked={runAllAccounts} onChange={e => setRunAllAccounts(e.target.checked)} className="accent-brand-gold" />
                All Accounts
              </label>
              <label className="flex items-center gap-2 text-xs text-brand-slate hover:text-[var(--foreground)] cursor-pointer">
                <input type="checkbox" checked={repairPrices} onChange={e => setRepairPrices(e.target.checked)} className="accent-brand-gold" />
                Repair Mode
              </label>
            </div>

            <button
              onClick={handleRecalculate}
              disabled={isRecalculating}
              className="w-full flex items-center justify-center gap-2 p-2.5 text-sm bg-brand-red hover:bg-[#6a1d28] text-white font-bold rounded-sm shadow-md transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${isRecalculating ? "animate-spin" : ""}`} />
              {isRecalculating ? "RECALCULATING..." : "⚡ RECALCULATE"}
            </button>
            
            {/* Data Maintenance Expander */}
            <div className="border border-[var(--border-color)] rounded overflow-hidden mt-3">
              <button 
                onClick={() => setExpanderData(!expanderData)}
                className="w-full flex items-center justify-between p-2 bg-[var(--border-color)]/20 hover:bg-[var(--border-color)]/40 text-xs font-semibold text-brand-slate transition-colors"
              >
                <div className="flex items-center gap-1"><Settings className="w-3 h-3" /> Data Maintenance</div>
                {expanderData ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              </button>
              {expanderData && (
                <div className="p-3 space-y-3 bg-[var(--background)] text-xs">
                  <button 
                    onClick={handleFlushCache}
                    disabled={isFlushing}
                    className="w-full p-1.5 border border-brand-slate/50 hover:bg-[var(--hover-bg)] text-brand-slate rounded flex items-center justify-center gap-1"
                  >
                    <Trash className="w-3 h-3" /> {isFlushing ? "Flushing..." : "Flush Local Cache"}
                  </button>
                  <div className="overflow-x-auto -mx-3 px-3 md:mx-0 md:px-0">
                    <p className="text-[10px] text-brand-slate mb-1">Latest Operations</p>
                    <table className="w-full text-left text-[10px] text-brand-slate border-collapse min-w-[200px]">
                      <thead>
                        <tr className="border-b border-[var(--border-color)]">
                          <th className="py-1">account</th>
                          <th className="py-1">run_type</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runLogs.map((log, i) => (
                          <tr key={i} className="border-b border-[var(--border-color)]/50">
                            <td className="py-1 pr-4">{log.account}</td>
                            <td className="py-1">{log.run_type}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </div>

          <hr className="border-[var(--border-color)]" />

          {/* Auto Refresh Schedule Expander */}
          <div className="border border-[var(--border-color)] rounded overflow-hidden">
            <button 
              onClick={() => setExpanderAuto(!expanderAuto)}
              className="w-full flex items-center justify-between p-2 bg-[var(--border-color)]/20 hover:bg-[var(--border-color)]/40 text-xs font-semibold text-brand-slate transition-colors"
            >
              <div className="flex items-center gap-1"><Clock className="w-3 h-3" /> Auto Refresh Schedule</div>
              {expanderAuto ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            </button>
            {expanderAuto && (
              <div className="p-3 space-y-3 bg-[var(--background)] text-xs">
                {arStatus.is_running ? (
                   <div className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 text-[10px] p-2 rounded flex items-center gap-2">
                     <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse"></div>
                     Active — runs daily at {String(arStatus.auto_refresh_hour).padStart(2,'0')}:{String(arStatus.auto_refresh_minute).padStart(2,'0')}
                   </div>
                ) : arStatus.auto_refresh_enabled ? (
                   <div className="bg-yellow-500/10 border border-yellow-500/20 text-yellow-500 text-[10px] p-2 rounded flex items-center gap-2">
                     <div className="w-2 h-2 bg-yellow-500 rounded-full"></div>
                     Enabled but thread inactive
                   </div>
                ) : (
                   <div className="bg-brand-slate/10 border border-brand-slate/20 text-brand-slate text-[10px] p-2 rounded flex items-center gap-2">
                     <div className="w-2 h-2 bg-brand-slate rounded-full"></div>
                     Disabled
                   </div>
                )}
                
                <label className="flex items-center gap-2 text-xs text-brand-slate hover:text-[var(--foreground)] cursor-pointer">
                  <input type="checkbox" checked={arEnabled} onChange={e => setArEnabled(e.target.checked)} className="accent-brand-gold" />
                  Enable auto refresh
                </label>

                <div>
                  <label className="text-[10px] text-brand-slate block mb-1">Run time (daily)</label>
                  <input 
                    type="time" 
                    value={arTime} 
                    onChange={e => setArTime(e.target.value)}
                    className="w-full bg-[var(--background)] border border-[var(--border-color)] text-brand-slate p-1.5 outline-none rounded"
                  />
                </div>

                <button 
                  onClick={handleSaveSchedule}
                  className="w-full py-1.5 bg-[var(--border-color)] hover:bg-[var(--foreground)] hover:text-[var(--background)] text-brand-slate transition-colors rounded"
                >
                  💾 Save & Apply
                </button>
              </div>
            )}
          </div>

        </div>
      </aside>

      {/* Toggle Button (Desktop) */}
      <div className="hidden md:block absolute top-4 left-4 z-30">
        {!sidebarOpen && (
          <button 
            onClick={() => setSidebarOpen(true)}
            className="p-2 bg-[var(--background)] border border-[var(--border-color)] rounded-md shadow-sm hover:border-brand-gold transition-colors"
          >
            <Search className="w-4 h-4 text-brand-slate" />
          </button>
        )}
      </div>

      {/* Toggle Button (Mobile FAB) */}
      {isMobile && !sidebarOpen && (
        <button 
          onClick={() => setSidebarOpen(true)}
          className="md:hidden fixed bottom-6 right-6 p-4 bg-brand-gold text-[var(--background)] rounded-full shadow-xl hover:bg-brand-gold-light transition-colors z-30"
          title="Portfolio Settings"
        >
          <Settings className="w-5 h-5" />
        </button>
      )}

      {/* MAIN CONTENT AREA */}
      <main className="flex-1 overflow-auto bg-[var(--background)] relative w-full">
        {/* HERO BANNER */}
        <div className="w-full h-[120px] md:h-[200px] border-y-[3px] border-brand-gold relative flex justify-end bg-[var(--background)] shrink-0">
          <div className="absolute left-4 md:left-16 bottom-4 md:bottom-8 z-10 pointer-events-none max-w-2xl">
            <h1 className="text-3xl md:text-5xl font-serif text-brand-gold mb-1 md:mb-2 drop-shadow-md tracking-tight">
              {mode === "dashboard" ? "Portfolio Dashboard" : 
               mode === "lookthrough" ? "Look-Through Analysis" : 
               mode === "optimization" ? "Portfolio Optimization" : 
               mode === "factors" ? "Factor Analysis" : 
               mode === "performance" ? "Performance Report" : "Trade Ingestion"}
            </h1>
            <p className="hidden md:block text-sm text-[var(--foreground)] max-w-xl font-light drop-shadow-sm">
              {mode === "dashboard" 
                ? "Track your real-time total valuation, Time-Weighted Return (TWR) performance, and underlying position weights."
                : mode === "lookthrough"
                ? "Analyze your portfolio's underlying ETF constituents, overlap, sector exposures, and P&L attribution."
                : mode === "optimization"
                ? "Construct optimal portfolios using Modern Portfolio Theory, run historical backtests, and simulate expected risk-adjusted returns."
                : mode === "factors"
                ? "Decompose portfolio returns using Fama-French multifactor regression to understand style biases and alpha generation."
                : mode === "performance"
                ? "Analyze your portfolio performance over custom time horizons, listing detailed cash flows, interest, dividends, and value changes in a Barclays-style consolidated view."
                : "Add new trades to a Live account ledger via PDF upload, bulk CSV processing, or manual entry."}
            </p>
          </div>
          {sidebarOpen && !isMobile && (
            <button 
              onClick={() => setSidebarOpen(false)}
              className="absolute left-4 top-4 p-2 bg-[var(--background)]/50 backdrop-blur-sm border border-[var(--border-color)] rounded-md shadow-sm hover:border-brand-gold transition-colors z-20 pointer-events-auto"
              title="Close Sidebar"
            >
              <svg className="w-4 h-4 text-brand-slate" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
              </svg>
            </button>
          )}
          <div className="relative w-full max-w-[800px] h-full">
            <img 
              src="/hero.png" 
              alt="Generated Coastal Scene" 
              className="w-full h-full object-cover object-[right_55%]"
            />
            <div className="absolute inset-0 bg-gradient-to-r from-[var(--background)] via-[var(--background)]/60 to-transparent pointer-events-none"></div>
          </div>
        </div>

        {/* CONTENT */}
        <div className="max-w-6xl mx-auto space-y-10 p-4 md:p-8 pt-6 md:pt-10">

          {isMobile && (mode === "ingestion" || mode === "lookthrough" || mode === "optimization" || mode === "factors") ? (
            <div className="flex flex-col items-center justify-center p-12 text-center border border-[var(--border-color)] bg-[var(--border-color)]/10 rounded-lg">
              <MonitorOff className="w-12 h-12 text-brand-slate mb-4" />
              <h3 className="text-xl font-serif text-[var(--foreground)] font-semibold mb-2">Best Viewed on Desktop</h3>
              <p className="text-sm text-brand-slate max-w-md">
                This complex analysis tool requires a larger screen for data tables and charts. Please access this page from a tablet or desktop computer.
              </p>
            </div>
          ) : (
            <React.Fragment key={refreshKey}>
              {mode === "dashboard" && (
                <PortfolioDashboard 
                  account={selectedAccount} 
                  synthetic_bm={selectedSynthetic} 
                  refreshKey={refreshKey}
                  onMissingStatus={(missing) => setIsSyntheticMissing(missing)}
                />
              )}
              {mode === "ingestion" && <TradeIngestion account={selectedAccount} />}
              {mode === "lookthrough" && <LookThroughSection account={selectedAccount} />}
              {mode === "optimization" && <PortfolioOptimization account={selectedAccount} />}
              {mode === "factors" && <FactorAnalysis account={selectedAccount} />}
              {mode === "performance" && <PerformanceAnalysis account={selectedAccount} />}
            </React.Fragment>
          )}
        </div>
      </main>
    </div>
  );
}

export default function PortfolioPage() {
  return (
    <Suspense fallback={<div className="p-8 text-brand-slate animate-pulse">Loading Portfolio...</div>}>
      <PortfolioContent />
    </Suspense>
  );
}
