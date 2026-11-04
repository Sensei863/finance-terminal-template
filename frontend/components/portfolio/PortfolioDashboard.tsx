import React, { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Settings, Save, RefreshCw, Database, ArrowUpCircle, ArrowDownCircle } from "lucide-react";

interface DashboardProps {
  account: string;
  synthetic_bm?: string;
  refreshKey?: number;
  onMissingStatus?: (missing: boolean) => void;
}

const _dashboardCache = new Map<string, any>();

const RetBox = ({ label, val, bVal }: { label: string, val: number | null, bVal?: number | null }) => {
  if (val === null || val === undefined) {
    return (
      <div className="bg-[var(--background)] p-4 rounded-md border border-[var(--border-color)] text-center shadow-sm">
        <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-1">{label}</div>
        <div className="text-xl font-bold font-sans text-brand-slate">N/A</div>
      </div>
    );
  }
  
  const isPos = val >= 0;
  const isRatio = label.includes("Ratio") || label.includes("Calmar");
  const isRisk = label.includes("VaR") || label.includes("Drawdown");
  
  let valColor = isPos ? "text-brand-green" : "text-brand-red";
  if (isRatio) valColor = "text-brand-green font-black";
  if (isRisk) valColor = "text-brand-red font-black";

  let valStr = "";
  if (isRatio) {
    valStr = val.toFixed(2);
  } else if (label.includes("Vol")) {
    valStr = `${(val * 100).toFixed(2)}%`;
  } else {
    valStr = `${isPos && !isRisk ? "+" : ""}${(val * 100).toFixed(2)}%`;
  }

  return (
    <div className="bg-[var(--background)] p-4 rounded-md border border-[var(--border-color)] text-center shadow-sm relative group">
      <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-1 truncate">{label}</div>
      <div className={`text-xl font-bold font-sans ${valColor}`}>
        {valStr}
      </div>
      {bVal !== undefined && bVal !== null && (
        <div className="text-[10px] text-brand-slate mt-1">
          Bench: <span className={bVal >= 0 && !isRisk ? "text-brand-green" : "text-brand-red"}>
            {isRatio ? bVal.toFixed(2) : `${bVal >= 0 && !isRisk ? "+" : ""}${(bVal * 100).toFixed(2)}%`}
          </span>
        </div>
      )}
    </div>
  );
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    let dateStr = label;
    if (typeof label === "number") {
      dateStr = new Date(label).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
    } else if (label) {
      dateStr = new Date(label).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
    }
    return (
      <div className="bg-[var(--background)] border border-[var(--border-color)] p-3 shadow-xl rounded-sm">
        <p className="text-brand-slate text-xs mb-2 font-mono font-medium">{dateStr}</p>
        {payload.map((entry: any, index: number) => (
          <p key={`item-${index}`} style={{ color: entry.color }} className="text-xs font-semibold flex items-center justify-between gap-4">
            <span>{entry.name}:</span>
            <span>{entry.value !== null && entry.value !== undefined ? Number(entry.value).toFixed(2) : "N/A"}</span>
          </p>
        ))}
      </div>
    );
  }
  return null;
};

export function PortfolioDashboard({ account, synthetic_bm, refreshKey = 0, onMissingStatus }: DashboardProps) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  
  const [chartHorizon, setChartHorizon] = useState<string>("MAX");
  const [benchmark, setBenchmark] = useState<string>("S&P 500 (IUSA.L)");

  useEffect(() => {
    if (!account) return;
    
    let ignore = false;
    setError("");
    let url = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/portfolio/dashboard?account=${encodeURIComponent(account)}`;
    
    const benchmarkTickerMatch = benchmark.match(/\(([^)]+)\)/);
    const benchmarkTicker = benchmarkTickerMatch ? benchmarkTickerMatch[1] : "IUSA.L";
    url += `&benchmark=${encodeURIComponent(benchmarkTicker)}`;
    
    if (synthetic_bm && synthetic_bm !== "None (use index line only)") {
      url += `&synthetic_bm=${encodeURIComponent(synthetic_bm)}`;
    }

    const cacheKey = `${url}::r=${refreshKey}`;
    const cached = _dashboardCache.get(cacheKey);
    if (cached) {
      setData(cached);
      if (synthetic_bm && synthetic_bm !== "None (use index line only)" && onMissingStatus) {
        const hasSynth = cached.chart_data && cached.chart_data.length > 0 && cached.chart_data[0].Synth_NAV !== undefined && cached.chart_data[0].Synth_NAV !== null;
        onMissingStatus(!hasSynth);
      } else if (onMissingStatus) {
        onMissingStatus(false);
      }
      setLastRefreshed(cached.run_timestamp ? new Date(cached.run_timestamp) : null);
      setLoading(false);
      return;
    }

    setLoading(true);
    
    fetch(url)
      .then(res => {
        if (!res.ok) throw new Error("Failed to load dashboard data");
        return res.json();
      })
      .then(d => {
        if (ignore) return;
        _dashboardCache.set(cacheKey, d);
        setData(d);
        
        if (synthetic_bm && synthetic_bm !== "None (use index line only)" && onMissingStatus) {
          // Check if Synth_NAV is actually in the returned chart_data
          const hasSynth = d.chart_data && d.chart_data.length > 0 && d.chart_data[0].Synth_NAV !== undefined && d.chart_data[0].Synth_NAV !== null;
          onMissingStatus(!hasSynth);
        } else if (onMissingStatus) {
          onMissingStatus(false);
        }
        
        setLastRefreshed(d.run_timestamp ? new Date(d.run_timestamp) : null);
        setLoading(false);
      })
      .catch(e => {
        if (ignore) return;
        setError(e.message);
        setLoading(false);
      });
      
    return () => { ignore = true; };
  }, [account, synthetic_bm, benchmark, refreshKey]);

  // removed diagnostic fetch functions


  if (loading) {
    return <div className="p-8 text-[var(--foreground)] animate-pulse font-serif tracking-widest uppercase">Loading Analytics...</div>;
  }

  if (error) {
    return <div className="p-8 text-brand-red border border-brand-red/20 bg-brand-red/5">{error}</div>;
  }

  if (!data) return null;

  const { metrics, chart_data, positions, currency_symbol = '£' } = data;
  
  const getFilteredChartData = () => {
    if (!chart_data) return [];
    
    let filtered = chart_data;
    if (chartHorizon !== "MAX") {
      const now = new Date(chart_data[chart_data.length - 1].date);
      let cutoffDate = new Date(now);
      
      switch(chartHorizon) {
        case "1M": cutoffDate.setMonth(cutoffDate.getMonth() - 1); break;
        case "3M": cutoffDate.setMonth(cutoffDate.getMonth() - 3); break;
        case "6M": cutoffDate.setMonth(cutoffDate.getMonth() - 6); break;
        case "1Y": cutoffDate.setFullYear(cutoffDate.getFullYear() - 1); break;
        case "2Y": cutoffDate.setFullYear(cutoffDate.getFullYear() - 2); break;
        case "5Y": cutoffDate.setFullYear(cutoffDate.getFullYear() - 5); break;
        case "YTD": cutoffDate = new Date(now.getFullYear(), 0, 1); break;
      }
      filtered = chart_data.filter((d: any) => new Date(d.date) >= cutoffDate);
    }
    
    if (filtered.length === 0) return [];

    // For horizons > 1 year (2Y, 5Y, MAX), apply uniform weekly sampling (Fridays + endpoints)
    if (chartHorizon === "2Y" || chartHorizon === "5Y" || chartHorizon === "MAX") {
      filtered = filtered.filter((d: any, idx: number) => {
        if (idx === 0 || idx === filtered.length - 1) return true;
        const day = new Date(d.date).getUTCDay();
        return day === 5; // Friday
      });
    }
    
    const base_twr = filtered[0].TWR_Index || 100;
    const base_bench = filtered[0].Bench_NAV || 100;
    const base_synth = filtered[0].Synth_NAV || 100;
    
    return filtered.map((d: any) => ({
      ...d,
      time: new Date(d.date).getTime(),
      TWR_Index_Norm: d.TWR_Index ? (d.TWR_Index / base_twr) * 100 : null,
      Bench_NAV_Norm: d.Bench_NAV ? (d.Bench_NAV / base_bench) * 100 : null,
      Synth_NAV_Norm: d.Synth_NAV ? (d.Synth_NAV / base_synth) * 100 : null,
    }));
  };

  const displayData = getFilteredChartData();

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      
      {lastRefreshed && (
        <div className="flex justify-start mb-2">
          <div className="text-[10px] text-brand-slate font-mono uppercase tracking-widest">
            Last Refreshed: {lastRefreshed.toLocaleString(undefined, {
              day: "2-digit",
              month: "2-digit",
              year: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit"
            })}
          </div>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm">
          <h3 className="text-[10px] uppercase tracking-widest text-brand-slate mb-2 font-semibold">Total Portfolio Value</h3>
          <div className="text-4xl font-serif text-[var(--foreground)]">{currency_symbol}{metrics.total_nav?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
        </div>
        <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm">
          <h3 className="text-[10px] uppercase tracking-widest text-brand-slate mb-2 font-semibold">Total Cash Deposited</h3>
          <div className="text-4xl font-serif text-[var(--foreground)]">{currency_symbol}{metrics.total_invested?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
        </div>
        <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm">
          <h3 className="text-[10px] uppercase tracking-widest text-brand-slate mb-2 font-semibold">Cash Balance</h3>
          <div className="text-4xl font-serif text-[var(--foreground)]">{currency_symbol}{metrics.cash?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
        </div>
      </div>

      {/* Performance Chart */}
      <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between mb-6 border-b border-[var(--border-color)] pb-4 gap-4">
          <h3 className="text-lg font-serif text-brand-gold">Time-Weighted Return (TWR) Tracker</h3>
          
          <div className="flex flex-col md:flex-row items-center gap-4">
            <select 
              value={benchmark}
              onChange={(e) => setBenchmark(e.target.value)}
              className="bg-[var(--background)] border border-[var(--border-color)] text-[var(--foreground)] text-xs px-3 py-1 outline-none focus:border-brand-gold font-sans"
            >
              <option value="S&P 500 (IUSA.L)">S&P 500 (IUSA.L)</option>
              <option value="MSCI World (SWDA.L)">MSCI World (SWDA.L)</option>
              <option value="Stoxx 600 (MEUD.L)">Stoxx 600 (MEUD.L)</option>
            </select>
            
            <div className="flex flex-wrap items-center bg-[var(--border-color)]/30 rounded-md p-0.5 gap-0.5">
              {['1M', '3M', '6M', 'YTD', '1Y', '2Y', '5Y', 'MAX'].map(hz => (
                <button
                  key={hz}
                  onClick={() => setChartHorizon(hz)}
                  className={`px-3 py-1 text-[10px] font-semibold tracking-wider transition-colors rounded-sm ${
                    chartHorizon === hz 
                      ? "bg-[var(--background)] text-[var(--foreground)] shadow-sm border border-[var(--border-color)]" 
                      : "text-brand-slate hover:text-[var(--foreground)]"
                  }`}
                >
                  {hz}
                </button>
              ))}
            </div>
          </div>
        </div>
        
        <div className="h-[400px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart 
              key={`${account}-${chartHorizon}-${benchmark}-${synthetic_bm || 'none'}`}
              data={displayData} 
              margin={{ top: 20, right: 30, left: 20, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
              <XAxis 
                dataKey="date" 
                stroke="var(--foreground)" 
                fontSize={11}
                minTickGap={35}
                tickFormatter={(val) => {
                  if (!val) return "";
                  const d = new Date(val);
                  if (chartHorizon === "1M" || chartHorizon === "3M" || chartHorizon === "6M") {
                    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
                  }
                  return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
                }}
              />
              <YAxis 
                stroke="var(--foreground)" 
                fontSize={12}
                domain={['auto', 'auto']}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend verticalAlign="top" height={36}/>
              <Line 
                type="monotone" 
                dataKey="TWR_Index_Norm"
                name="Portfolio TWR"
                stroke="#cfa144"
                strokeWidth={2}
                dot={false}
                connectNulls={true}
                isAnimationActive={true}
                animationDuration={900}
                animationEasing="ease-out"
                activeDot={{ r: 6, fill: "#cfa144", stroke: "var(--background)", strokeWidth: 2 }}
              />
              {displayData && displayData.length > 0 && displayData[0].Bench_NAV !== undefined && (
                <Line 
                  type="monotone" 
                  dataKey="Bench_NAV_Norm"
                  name={benchmark}
                  stroke="#5b7c99"
                  strokeWidth={2}
                  dot={false}
                  connectNulls={true}
                  isAnimationActive={true}
                  animationDuration={900}
                  animationEasing="ease-out"
                  activeDot={{ r: 6 }}
                />
              )}
              {displayData && displayData.length > 0 && displayData[0].Synth_NAV !== undefined && displayData[0].Synth_NAV !== null && (
                <Line 
                  type="monotone" 
                  dataKey="Synth_NAV_Norm"
                  name={synthetic_bm && synthetic_bm !== "None (use index line only)" ? synthetic_bm : "Synthetic"}
                  stroke="#0ea5e9"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={false}
                  connectNulls={true}
                  isAnimationActive={true}
                  animationDuration={900}
                  animationEasing="ease-out"
                  activeDot={{ r: 6 }}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Quantitative Analytics Section */}
      <div className="space-y-8 mt-8">
        <div>
          <h3 className="text-xl font-serif text-[var(--foreground)] mb-1">Quantitative Analytics</h3>
          <p className="text-xs text-brand-slate mb-4">Risk metrics and performance ratios calculated on a 5-Year window.</p>
        </div>

        {/* Row 1: Period Returns */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <RetBox label="1 Month" val={metrics.returns?.["1M"]} bVal={metrics.bench_returns?.["1M"]} />
          <RetBox label="3 Months" val={metrics.returns?.["3M"]} bVal={metrics.bench_returns?.["3M"]} />
          <RetBox label="6 Months" val={metrics.returns?.["6M"]} bVal={metrics.bench_returns?.["6M"]} />
          <RetBox label="1 Year" val={metrics.returns?.["1Y"]} bVal={metrics.bench_returns?.["1Y"]} />
          <RetBox label="CAGR (Ann.)" val={metrics.returns?.["CAGR"]} bVal={metrics.bench_returns?.["CAGR"]} />
        </div>

        {/* Row 2: Calendar Year Returns */}
        {metrics.calendar_returns && Object.keys(metrics.calendar_returns).length > 0 && (
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wider text-brand-slate mb-3 border-b border-[var(--border-color)] pb-2">Calendar Year Returns</h4>
            <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
              {Object.keys(metrics.calendar_returns).map(yr => (
                <RetBox 
                  key={yr} 
                  label={yr} 
                  val={metrics.calendar_returns[yr]} 
                  bVal={metrics.bench_calendar_returns?.[yr]} 
                />
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {/* Row 3A: Drawdown Profile */}
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wider text-brand-slate mb-3 border-b border-[var(--border-color)] pb-2">Drawdown Profile</h4>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <RetBox label="Current DD" val={metrics.risk?.["Curr_DD"]} bVal={metrics.bench_risk?.["Curr_DD"]} />
              <RetBox label="Max DD (All)" val={metrics.risk?.["Max_DD_All"]} bVal={metrics.bench_risk?.["Max_DD_All"]} />
              <RetBox label="Max DD (1Y)" val={metrics.risk?.["Max_DD_1Y"]} bVal={metrics.bench_risk?.["Max_DD_1Y"]} />
            </div>
          </div>

          {/* Row 3B: Risk Metrics */}
          <div>
            <h4 className="text-sm font-semibold uppercase tracking-wider text-brand-slate mb-3 border-b border-[var(--border-color)] pb-2">Risk Metrics</h4>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <RetBox label="Ann. Volatility" val={metrics.risk?.["Ann_Vol"]} bVal={metrics.bench_risk?.["Ann_Vol"]} />
              <RetBox label="VaR (95%)" val={metrics.risk?.["VaR_95"]} bVal={metrics.bench_risk?.["VaR_95"]} />
              <RetBox label="Cond. VaR" val={metrics.risk?.["CVaR_95"]} bVal={metrics.bench_risk?.["CVaR_95"]} />
            </div>
          </div>
        </div>

        {/* Row 4: Advanced Ratios */}
        <div>
          <h4 className="text-sm font-semibold uppercase tracking-wider text-brand-slate mb-3 border-b border-[var(--border-color)] pb-2">Advanced Ratios</h4>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <RetBox label="Sharpe Ratio" val={metrics.ratios?.["Sharpe"]} bVal={metrics.bench_ratios?.["Sharpe"]} />
            <RetBox label="Sortino Ratio" val={metrics.ratios?.["Sortino"]} bVal={metrics.bench_ratios?.["Sortino"]} />
            <RetBox label="Calmar Ratio" val={metrics.ratios?.["Calmar"]} bVal={metrics.bench_ratios?.["Calmar"]} />
          </div>
        </div>
      </div>

      {/* Positions Table */}
      <div className="bg-[var(--background)] border border-[var(--border-color)] shadow-sm mt-8">
        <div className="p-6 border-b border-[var(--border-color)]">
          <h3 className="text-lg font-serif text-brand-gold">Current Holdings</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[var(--border-color)] bg-[var(--hover-bg)]">
                <th className="p-4 text-xs uppercase tracking-wider text-brand-slate font-semibold">Ticker</th>
                <th className="p-4 text-xs uppercase tracking-wider text-brand-slate font-semibold text-right">Shares</th>
                <th className="p-4 text-xs uppercase tracking-wider text-brand-slate font-semibold text-right">Last Price ({currency_symbol})</th>
                <th className="p-4 text-xs uppercase tracking-wider text-brand-slate font-semibold text-right">Value ({currency_symbol})</th>
                <th className="p-4 text-xs uppercase tracking-wider text-brand-slate font-semibold text-right">Weight (%)</th>
              </tr>
            </thead>
            <tbody>
              {positions.sort((a:any, b:any) => b.value - a.value).map((pos: any, idx: number) => (
                <tr key={pos.ticker} className="border-b border-[var(--border-color)] hover:bg-brand-gold/10 transition-colors">
                  <td className="p-4 text-sm font-semibold text-[var(--foreground)]">{pos.ticker}</td>
                  <td className="p-4 text-sm text-[var(--foreground)] text-right">{pos.shares.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</td>
                  <td className="p-4 text-sm text-[var(--foreground)] text-right">{pos.price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</td>
                  <td className="p-4 text-sm text-[var(--foreground)] text-right">{pos.value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                  <td className="p-4 text-sm font-mono text-brand-gold text-right">{pos.weight.toFixed(2)}%</td>
                </tr>
              ))}
              {positions.length === 0 && (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-brand-slate text-sm">No active holdings found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Diagnostics panel has been moved to the Settings -> Diagnostics & Toolkit page */}

    </div>
  );
}
