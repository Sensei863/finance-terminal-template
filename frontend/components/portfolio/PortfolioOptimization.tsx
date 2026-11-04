"use client";

import React, { useState, useEffect } from "react";
import { 
  BarChart2, 
  Settings2, 
  Target, 
  Activity, 
  TrendingUp, 
  RefreshCw, 
  Search,
  Plus,
  Trash
} from "lucide-react";
import { 
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Cell, ReferenceDot,
  LineChart, Line, AreaChart, Area, Legend
} from "recharts";

interface OptimizationProps {
  account: string;
}

export function PortfolioOptimization({ account }: OptimizationProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [configOpen, setConfigOpen] = useState(true);

  // Universe
  const [availableTickers, setAvailableTickers] = useState<string[]>([]);
  const [selectedTickers, setSelectedTickers] = useState<string[]>([]);
  
  // Hypothetical
  const [hypoInput, setHypoInput] = useState("");
  const [hypoTickers, setHypoTickers] = useState<string[]>([]);
  const [resolving, setResolving] = useState(false);

  // Settings
  const [lookback, setLookback] = useState(3);
  const [optMode, setOptMode] = useState("Max Sharpe");
  const [overrides, setOverrides] = useState<Record<string, number>>({});
  
  // Results
  const [results, setResults] = useState<any>(null);
  const [historicalReturns, setHistoricalReturns] = useState<Record<string, number>>({});

  useEffect(() => {
    async function fetchHistoricalReturns() {
      const allTickers = Array.from(new Set([...selectedTickers, ...hypoTickers]));
      if (allTickers.length === 0) {
        setHistoricalReturns({});
        return;
      }
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/optimization/historical-returns`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            account,
            tickers: selectedTickers,
            hypothetical_tickers: hypoTickers,
            lookback_years: lookback,
            opt_mode: "Max Sharpe"
          })
        });
        if (res.ok) {
          const data = await res.json();
          setHistoricalReturns(data);
        }
      } catch (e) {
        console.error("Failed to fetch historical returns", e);
      }
    }
    fetchHistoricalReturns();
  }, [account, selectedTickers, hypoTickers, lookback]);

  useEffect(() => {
    async function fetchUniverse() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/optimization/held-tickers`);
        if (res.ok) {
          const data = await res.json();
          setAvailableTickers(data.tickers || []);
          setSelectedTickers(data.tickers || []);
        }
      } catch (e) {
        console.error(e);
      }
    }
    fetchUniverse();
  }, []);

  const handleResolveHypo = async () => {
    if (!hypoInput.trim()) return;
    setResolving(true);
    try {
      const names = hypoInput.split(",").map(s => s.trim()).filter(Boolean);
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/ingestion/resolve-tickers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account, asset_names: names })
      });
      if (res.ok) {
        const data = await res.json();
        const resolvedList = Object.values(data.resolved) as string[];
        const validTickers = resolvedList.filter(Boolean);
        const newHypos = Array.from(new Set([...hypoTickers, ...validTickers]));
        setHypoTickers(newHypos);
        setHypoInput("");
      }
    } catch (e) {
      console.error(e);
    } finally {
      setResolving(false);
    }
  };

  const removeHypo = (t: string) => {
    setHypoTickers(prev => prev.filter(x => x !== t));
  };

  const handleRunOptimization = async () => {
    if (selectedTickers.length === 0 && hypoTickers.length === 0) {
      setError("Please select at least one asset.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/optimization/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account,
          tickers: selectedTickers,
          hypothetical_tickers: hypoTickers,
          lookback_years: lookback,
          opt_mode: optMode,
          return_overrides: Object.keys(overrides).length > 0 ? overrides : null
        })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to run optimization");
      }
      const data = await res.json();
      setResults(data);
      setConfigOpen(false);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleOverrideChange = (ticker: string, val: string) => {
    const num = parseFloat(val);
    setOverrides(prev => {
      const next = { ...prev };
      if (isNaN(num)) {
        delete next[ticker];
      } else {
        next[ticker] = num / 100; // convert % to decimal
      }
      return next;
    });
  };

  const renderColorMatrix = (values: number[][], index: number, colIndex: number) => {
    const val = values[index][colIndex];
    if (val === 1) return 'bg-brand-navy-light text-brand-cream';
    if (val > 0.5) return 'bg-brand-green/80 text-white';
    if (val > 0) return 'bg-brand-green/40 text-[var(--foreground)]';
    if (val > -0.5) return 'bg-brand-red/40 text-[var(--foreground)]';
    return 'bg-brand-red/80 text-white';
  };

  const formatPct = (val: number) => `${(val * 100).toFixed(2)}%`;

  return (
    <div className="space-y-6 animate-in fade-in duration-500 pt-6">
      
      {/* Configuration Panel */}
      <details 
        className="group bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl overflow-hidden shadow-sm"
        open={configOpen}
      >
        <summary 
          className="px-6 py-4 cursor-pointer flex items-center justify-between hover:bg-[var(--hover-bg)] transition-colors list-none"
          onClick={(e) => {
            e.preventDefault();
            setConfigOpen(!configOpen);
          }}
        >
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-brand-gold/10 text-brand-gold">
              <Settings2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-[var(--foreground)]">Optimization Settings</h3>
              <p className="text-xs text-brand-slate font-light">Configure lookback, objective, and asset universe</p>
            </div>
          </div>
          <div className="text-brand-slate group-open:rotate-180 transition-transform duration-300">
            ▼
          </div>
        </summary>
        
        <div className="p-6 border-t border-[var(--border-color)] space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Core Settings */}
            <div className="space-y-4">
              <h4 className="text-[10px] uppercase tracking-wider text-brand-slate font-bold">Parameters</h4>
              
              <div className="space-y-2">
                <label className="text-sm font-medium text-[var(--foreground)]">Objective</label>
                <div className="flex flex-col gap-2">
                  {["Max Sharpe", "Min Volatility", "Target Risk (Match Current)"].map(m => (
                    <label key={m} className="flex items-center gap-2 text-sm text-brand-slate cursor-pointer">
                      <input 
                        type="radio" 
                        name="optMode" 
                        className="accent-brand-gold"
                        checked={optMode === m}
                        onChange={() => setOptMode(m)}
                      />
                      {m}
                    </label>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-[var(--foreground)] flex justify-between">
                  <span>Lookback Period</span>
                  <span className="text-brand-gold">{lookback} Years</span>
                </label>
                <input 
                  type="range" 
                  min="1" max="10" step="1"
                  value={lookback}
                  onChange={e => setLookback(parseInt(e.target.value))}
                  className="w-full accent-brand-gold"
                />
              </div>
            </div>

            {/* Asset Universe */}
            <div className="space-y-4">
              <h4 className="text-[10px] uppercase tracking-wider text-brand-slate font-bold">Current Holdings</h4>
              <div className="max-h-40 overflow-y-auto pr-2 space-y-1">
                {availableTickers.map(t => (
                  <label key={t} className="flex items-center gap-2 text-xs text-[var(--foreground)] cursor-pointer p-1 hover:bg-[var(--hover-bg)] rounded">
                    <input 
                      type="checkbox" 
                      className="accent-brand-gold rounded"
                      checked={selectedTickers.includes(t)}
                      onChange={(e) => {
                        if (e.target.checked) setSelectedTickers([...selectedTickers, t]);
                        else setSelectedTickers(selectedTickers.filter(x => x !== t));
                      }}
                    />
                    {t}
                  </label>
                ))}
              </div>
            </div>

            {/* Hypothetical Assets */}
            <div className="space-y-4">
              <h4 className="text-[10px] uppercase tracking-wider text-brand-slate font-bold">Hypothetical Assets</h4>
              <div className="flex gap-2">
                <input 
                  type="text" 
                  placeholder="e.g. Apple, Bitcoin, VOO" 
                  value={hypoInput}
                  onChange={(e) => setHypoInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleResolveHypo()}
                  className="flex-1 bg-transparent border border-[var(--border-color)] rounded px-3 py-1.5 text-sm text-[var(--foreground)] focus:outline-none focus:border-brand-gold"
                />
                <button 
                  onClick={handleResolveHypo}
                  disabled={resolving || !hypoInput.trim()}
                  className="bg-[var(--border-color)] hover:bg-brand-gold hover:text-white text-[var(--foreground)] px-3 py-1.5 rounded transition-colors disabled:opacity-50"
                >
                  {resolving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                {hypoTickers.map(t => (
                  <span key={t} className="inline-flex items-center gap-1 px-2 py-1 bg-brand-gold/10 text-brand-gold text-xs rounded border border-brand-gold/20">
                    {t}
                    <button onClick={() => removeHypo(t)} className="hover:text-brand-red"><Trash className="w-3 h-3"/></button>
                  </span>
                ))}
              </div>
            </div>

            {/* Expected Return Overrides */}
            {Object.keys(historicalReturns).length > 0 && (
              <div className="md:col-span-3 space-y-4 pt-4 border-t border-[var(--border-color)]">
                <h4 className="text-[10px] uppercase tracking-wider text-brand-slate font-bold">Expected Return Overrides</h4>
                <p className="text-xs text-brand-slate font-light">Historical returns (especially for niche ETFs) can be extreme. Tweak them below to see a more realistic Frontier.</p>
                <div className="overflow-x-auto border border-[var(--border-color)] rounded-lg">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-[var(--border-color)]/30">
                      <tr>
                        <th className="px-4 py-2 font-medium text-brand-slate">Ticker</th>
                        <th className="px-4 py-2 font-medium text-brand-slate text-right">Historical Return</th>
                        <th className="px-4 py-2 font-medium text-brand-slate text-right">Override Return (%)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-color)]">
                      {Object.entries(historicalReturns).map(([ticker, ret]) => (
                        <tr key={ticker} className="hover:bg-[var(--hover-bg)] transition-colors">
                          <td className="px-4 py-2 font-medium text-[var(--foreground)]">{ticker}</td>
                          <td className="px-4 py-2 text-right text-[var(--foreground)]">{formatPct(ret)}</td>
                          <td className="px-4 py-2 text-right flex justify-end">
                            <input 
                              type="number" 
                              step="0.01" 
                              placeholder={(ret * 100).toFixed(2)}
                              value={overrides[ticker] !== undefined ? (overrides[ticker] * 100).toFixed(2) : ""}
                              onChange={(e) => handleOverrideChange(ticker, e.target.value)}
                              className="w-24 bg-transparent border border-[var(--border-color)] rounded px-2 py-1 text-right focus:outline-none focus:border-brand-gold"
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          <div className="pt-4 border-t border-[var(--border-color)] flex items-center justify-between">
            <p className="text-xs text-brand-slate">
              Engine calculates covariance matrix based on daily returns for the selected window.
            </p>
            <button 
              onClick={handleRunOptimization}
              disabled={loading}
              className="bg-brand-gold hover:bg-brand-gold-dark text-white px-6 py-2 rounded-lg font-medium transition-colors flex items-center gap-2 disabled:opacity-50"
            >
              {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
              {loading ? "Optimizing..." : "Run Optimization"}
            </button>
          </div>
          
          {error && (
            <div className="p-3 bg-brand-red/10 border border-brand-red/20 rounded text-brand-red text-sm">
              {error}
            </div>
          )}
        </div>
      </details>

      {/* Results View */}
      {results && (
        <div className="space-y-8 animate-in slide-in-from-bottom-4 duration-500">
          
          {/* Key Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
              <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-2">Target Return</div>
              <div className="text-3xl font-serif text-[var(--foreground)]">{formatPct(results.target_portfolio.return)}</div>
              <div className="text-xs text-brand-slate mt-1">Annualized Expected</div>
            </div>
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
              <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-2">Volatility (Risk)</div>
              <div className="text-3xl font-serif text-[var(--foreground)]">{formatPct(results.target_portfolio.volatility)}</div>
              <div className="text-xs text-brand-slate mt-1">Annualized Std Dev</div>
            </div>
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
              <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-2">Sharpe Ratio</div>
              <div className="text-3xl font-serif text-brand-gold">{results.target_portfolio.sharpe.toFixed(2)}</div>
              <div className="text-xs text-brand-slate mt-1">Risk-Adjusted Performance</div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Efficient Frontier Chart */}
            <div className="lg:col-span-2 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
              <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--foreground)] border-b border-[var(--border-color)] pb-3 mb-6">
                Efficient Frontier
              </h3>
              <div className="h-[400px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" opacity={0.5} />
                    <XAxis 
                      type="number" 
                      dataKey="Volatility" 
                      name="Risk (Vol)" 
                      domain={['auto', 'auto']} 
                      tickFormatter={(v) => `${(v*100).toFixed(0)}%`}
                      stroke="var(--foreground)"
                      fontSize={12}
                    />
                    <YAxis 
                      type="number" 
                      dataKey="Return" 
                      name="Return" 
                      domain={['auto', 'auto']}
                      tickFormatter={(v) => `${(v*100).toFixed(0)}%`}
                      stroke="var(--foreground)"
                      fontSize={12}
                    />
                    <RechartsTooltip 
                      cursor={{ strokeDasharray: '3 3' }}
                      content={({ active, payload }) => {
                        if (active && payload && payload.length) {
                          const data = payload[0].payload;
                          return (
                            <div className="bg-[var(--background)] border border-[var(--border-color)] p-4 shadow-xl text-xs">
                              <p className="font-bold text-brand-gold mb-1">{data.ticker || "Portfolio"}</p>
                              <p className="text-[var(--foreground)] text-sm font-semibold">Return: {formatPct(data.Return || data.return)}</p>
                              <p className="text-[var(--foreground)] text-sm font-semibold">Risk: {formatPct(data.Volatility || data.volatility)}</p>
                            </div>
                          );
                        }
                        return null;
                      }}
                    />
                    {/* The Frontier Curve */}
                    <Scatter name="Frontier" data={results.frontier} fill="#cfa144" line={{ stroke: "#cfa144", strokeWidth: 2 }} shape="circle" />
                    
                    {/* Individual Assets */}
                    <Scatter name="Assets" data={results.individual_assets.map((a: any) => ({ ...a, Return: a.return, Volatility: a.volatility }))} fill="#94a3b8" />
                    
                    {/* Target Portfolio Star */}
                    <ReferenceDot 
                      x={results.target_portfolio.volatility} 
                      y={results.target_portfolio.return} 
                      r={8} 
                      fill="#2d7a4f" 
                      stroke="white" 
                      strokeWidth={2}
                      shape={(props: any) => (
                        <polygon points="0,-10 3,-3 10,-3 4,2 6,9 0,5 -6,9 -4,2 -10,-3 -3,-3" fill="#2d7a4f" transform={`translate(${props.cx}, ${props.cy})`} />
                      )}
                    />

                    {/* Current Portfolio Square */}
                    {results.current_portfolios?.[account] && (
                       <ReferenceDot 
                         x={results.current_portfolios[account].Volatility} 
                         y={results.current_portfolios[account].Return} 
                         r={6} 
                         fill="#1B2A41" 
                         stroke="#f8f6f0" 
                         strokeWidth={1}
                         shape={(props: any) => (
                           <rect x={props.cx - 5} y={props.cy - 5} width={10} height={10} fill="#1B2A41" stroke="#f8f6f0"/>
                         )}
                       />
                    )}
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Weights Table */}
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl flex flex-col shadow-sm overflow-hidden">
              <div className="p-4 border-b border-[var(--border-color)]">
                 <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--foreground)]">Optimal Allocation</h3>
              </div>
              <div className="flex-1 overflow-y-auto">
                <table className="w-full text-xs text-left">
                  <thead className="bg-[var(--border-color)]/30 sticky top-0 z-10">
                    <tr>
                      <th className="px-4 py-2 font-medium text-brand-slate uppercase tracking-wider">Asset</th>
                      <th className="px-4 py-2 font-medium text-brand-slate uppercase tracking-wider text-right">Optimal</th>
                      <th className="px-4 py-2 font-medium text-brand-slate uppercase tracking-wider text-right">Current</th>
                      <th className="px-4 py-2 font-medium text-brand-slate uppercase tracking-wider text-right">Delta</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-color)]">
                    {Object.entries(results.target_portfolio.weights)
                      .filter(([_, w]: [string, any]) => w > 0.001 || (results.current_portfolios?.[account]?.Weights?.[_] > 0.001))
                      .sort(([_, a]: [string, any], [__, b]: [string, any]) => b - a)
                      .map(([ticker, weight]: [string, any]) => {
                        const curr = results.current_portfolios?.[account]?.Weights?.[ticker] || 0;
                        const delta = weight - curr;
                        return (
                          <tr key={ticker} className="hover:bg-[var(--hover-bg)] transition-colors">
                            <td className="px-4 py-3 font-medium text-[var(--foreground)]">{ticker}</td>
                            <td className="px-4 py-3 text-right text-brand-gold font-medium">{formatPct(weight)}</td>
                            <td className="px-4 py-3 text-right text-brand-slate">{formatPct(curr)}</td>
                            <td className={`px-4 py-3 text-right font-medium ${delta > 0.001 ? 'text-brand-green' : delta < -0.001 ? 'text-brand-red' : 'text-brand-slate'}`}>
                              {delta > 0 ? "+" : ""}{formatPct(delta)}
                            </td>
                          </tr>
                        );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Correlation Matrix Heatmap */}
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm overflow-x-auto">
              <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--foreground)] border-b border-[var(--border-color)] pb-3 mb-6">
                Correlation Heatmap
              </h3>
              <div className="min-w-max">
                <table className="w-full text-[10px]">
                  <thead>
                    <tr>
                      <th className="p-1"></th>
                      {results.correlation_matrix.tickers.map((t: string) => (
                        <th key={t} className="p-1 text-brand-slate font-medium truncate max-w-[60px]" title={t}>{t}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {results.correlation_matrix.tickers.map((rowTicker: string, i: number) => (
                      <tr key={rowTicker}>
                        <th className="p-1 text-right text-brand-slate font-medium truncate max-w-[60px]" title={rowTicker}>{rowTicker}</th>
                        {results.correlation_matrix.tickers.map((_: any, j: number) => {
                          const val = results.correlation_matrix.values[i][j];
                          return (
                            <td key={j} className="p-0.5">
                              <div className={`w-10 h-8 flex items-center justify-center rounded text-xs font-medium ${renderColorMatrix(results.correlation_matrix.values, i, j)}`}>
                                {val.toFixed(2)}
                              </div>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Backtest Chart */}
            {results.backtest && results.backtest.length > 0 && (
              <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
                <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--foreground)] border-b border-[var(--border-color)] pb-3 mb-6">
                  Historical Backtest (Normalized to 1.0)
                </h3>
                <div className="h-[400px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={results.backtest} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
                      <XAxis 
                        dataKey="date" 
                        stroke="var(--foreground)" 
                        fontSize={12} 
                        tickFormatter={(val) => {
                          if (!val) return "";
                          const d = new Date(val);
                          return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
                        }}
                      />
                      <YAxis 
                        stroke="var(--foreground)" 
                        fontSize={12} 
                        domain={['auto', 'auto']} 
                        tickFormatter={(v) => v.toFixed(2)} 
                      />
                      <RechartsTooltip 
                        content={({ active, payload, label }) => {
                          if (active && payload && payload.length) {
                            return (
                              <div className="bg-[var(--background)] border border-[var(--border-color)] p-4 shadow-xl">
                                <p className="text-brand-slate text-xs mb-2">{label}</p>
                                {payload.map((entry: any, index: number) => (
                                  <p key={`item-${index}`} style={{ color: entry.color }} className="text-sm font-semibold">
                                    {entry.name}: {entry.value?.toFixed(2)}
                                  </p>
                                ))}
                              </div>
                            );
                          }
                          return null;
                        }}
                      />
                      <Legend verticalAlign="top" height={36}/>
                      <Line 
                        type="monotone" 
                        dataKey="target" 
                        name="Optimal Portfolio" 
                        stroke="#cfa144" 
                        strokeWidth={2} 
                        dot={false}
                        isAnimationActive={false}
                        activeDot={{ r: 6, fill: "#cfa144", stroke: "var(--background)", strokeWidth: 2 }}
                      />
                      <Line 
                        type="monotone" 
                        dataKey="current" 
                        name="Current Portfolio" 
                        stroke="#5b7c99" 
                        strokeWidth={2} 
                        dot={false} 
                        strokeDasharray="5 5"
                        isAnimationActive={false}
                        activeDot={{ r: 6 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>

        </div>
      )}
    </div>
  );
}
