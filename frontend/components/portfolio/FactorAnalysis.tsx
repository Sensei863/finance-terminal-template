"use client";

import React, { useState, useEffect } from "react";
import { 
  Activity, 
  RefreshCw,
  Info
} from "lucide-react";
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Cell, ReferenceLine,
  LineChart, Line, Legend
} from "recharts";

interface FactorAnalysisProps {
  account: string;
}

export function FactorAnalysis({ account }: FactorAnalysisProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form State
  const [modelType, setModelType] = useState("5-Factor");
  const [frequency, setFrequency] = useState("Weekly (Resampled)");
  
  // Date State - Default to last 3 years
  const today = new Date();
  const threeYearsAgo = new Date();
  threeYearsAgo.setFullYear(today.getFullYear() - 3);
  
  const [startDate, setStartDate] = useState(threeYearsAgo.toISOString().split("T")[0]);
  const [endDate, setEndDate] = useState(today.toISOString().split("T")[0]);

  // Results
  const [results, setResults] = useState<any>(null);
  const [rollingResults, setRollingResults] = useState<any[]>([]);

  const handleRunAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      const [resRun, resRolling] = await Promise.all([
        fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/factors/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            account,
            model_type: modelType,
            frequency,
            start_date: startDate,
            end_date: endDate
          })
        }),
        fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/factors/rolling`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            account,
            model_type: modelType,
            frequency,
            start_date: startDate,
            end_date: endDate,
            window: 60
          })
        })
      ]);

      if (!resRun.ok) {
        const err = await resRun.json();
        throw new Error(err.detail || "Failed to run factor analysis");
      }
      const data = await resRun.json();
      setResults(data);

      if (resRolling.ok) {
        const rollingData = await resRolling.json();
        setRollingResults(rollingData.data || []);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const factorColors: Record<string, string> = {
    "Alpha": "#cfa144",
    "Mkt-RF": "#1B2A41",
    "SMB": "#8a9bb0",
    "HML": "#2d7a4f",
    "RMW": "#8b2635",
    "CMA": "#d35400"
  };

  const getSigColor = (sig: string) => {
    if (sig.includes("1%")) return "bg-brand-green";
    if (sig.includes("5%")) return "bg-brand-green/60";
    if (sig.includes("10%")) return "bg-brand-gold";
    return "bg-brand-slate";
  };

  // Convert loadings dictionary to array for the bar chart
  const loadingsData = results 
    ? Object.entries(results.loadings)
        .filter(([k]) => k !== "Alpha")
        .map(([k, v]: [string, any]) => ({ name: k, ...v }))
    : [];

  return (
    <div className="space-y-6 animate-in fade-in duration-500 pt-6">
      
      {/* Controls Row */}
      <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-end">
          
          <div className="space-y-2 md:col-span-3">
            <label className="text-sm font-medium text-brand-slate uppercase tracking-wider text-[10px]">Factor Model</label>
            <select 
              value={modelType}
              onChange={(e) => setModelType(e.target.value)}
              className="w-full bg-transparent border border-[var(--border-color)] rounded-lg px-3 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:border-brand-gold"
            >
              <option value="3-Factor">3-Factor (Market, Size, Value)</option>
              <option value="5-Factor">5-Factor (Adds Profitability, Investment)</option>
            </select>
          </div>

          <div className="space-y-2 md:col-span-3">
            <label className="text-sm font-medium text-brand-slate uppercase tracking-wider text-[10px]">Frequency</label>
            <select 
              value={frequency}
              onChange={(e) => setFrequency(e.target.value)}
              className="w-full bg-transparent border border-[var(--border-color)] rounded-lg px-3 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:border-brand-gold"
            >
              <option value="Daily">Daily</option>
              <option value="Weekly (Resampled)">Weekly (Resampled)</option>
              <option value="Monthly">Monthly</option>
            </select>
          </div>

          <div className="space-y-2 md:col-span-4">
            <label className="text-sm font-medium text-brand-slate uppercase tracking-wider text-[10px]">Date Range</label>
            <div className="flex items-center gap-2">
              <input 
                type="date" 
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full bg-transparent border border-[var(--border-color)] rounded-lg px-2 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:border-brand-gold"
              />
              <span className="text-brand-slate">-</span>
              <input 
                type="date" 
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full bg-transparent border border-[var(--border-color)] rounded-lg px-2 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:border-brand-gold"
              />
            </div>
          </div>

          <div className="md:col-span-2">
            <button 
              onClick={handleRunAnalysis}
              disabled={loading}
              className="w-full bg-brand-gold hover:bg-brand-gold-dark text-white px-6 py-2 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
            >
              {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
              {loading ? "Running..." : "Run Analysis"}
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 p-3 bg-brand-red/10 border border-brand-red/20 rounded text-brand-red text-sm">
            {error}
          </div>
        )}
      </div>

      {results && (
        <div className="space-y-8 animate-in slide-in-from-bottom-4 duration-500">
          
          {/* Metrics Scorecard */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm relative overflow-hidden">
              <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-2">Annualized Alpha</div>
              <div className="text-3xl font-serif text-brand-gold">{(results.annualized_alpha * 100).toFixed(2)}%</div>
              <div className="flex items-center gap-2 mt-2">
                <span className={`w-2 h-2 rounded-full ${getSigColor(results.alpha_significance)}`}></span>
                <span className="text-xs text-brand-slate">{results.alpha_significance}</span>
              </div>
            </div>
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
              <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-2">R-Squared</div>
              <div className="text-3xl font-serif text-[var(--foreground)]">{(results.r_squared * 100).toFixed(1)}%</div>
              <div className="text-xs text-brand-slate mt-2">Variance Explained</div>
            </div>
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
              <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-2">Adj R-Squared</div>
              <div className="text-3xl font-serif text-[var(--foreground)]">{(results.adj_r_squared * 100).toFixed(1)}%</div>
              <div className="text-xs text-brand-slate mt-2">Penalty for added factors</div>
            </div>
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
              <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-2">Observations</div>
              <div className="text-3xl font-serif text-[var(--foreground)]">{results.n_obs}</div>
              <div className="text-xs text-brand-slate mt-2">{frequency.split(" ")[0]} periods</div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            
            {/* Factor Loadings (Beta) Bar Chart */}
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
              <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--foreground)] border-b border-[var(--border-color)] pb-3 mb-6 flex items-center gap-2">
                Factor Loadings (Beta)
                <span className="text-brand-slate" title="Sensitivities to specific Fama-French factors"><Info className="w-4 h-4"/></span>
              </h3>
              <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={loadingsData} layout="vertical" margin={{ top: 0, right: 30, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" horizontal={false} opacity={0.5} />
                    <XAxis type="number" stroke="var(--brand-slate)" fontSize={10} />
                    <YAxis dataKey="name" type="category" stroke="var(--brand-slate)" fontSize={10} width={60} />
                    <RechartsTooltip 
                      contentStyle={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border-color)', borderRadius: '8px' }}
                      itemStyle={{ fontSize: '12px' }}
                      formatter={(value: any, name: any, props: any) => [
                        `${value.toFixed(4)} (t=${props.payload.t_stat.toFixed(2)})`, 
                        "Beta"
                      ]}
                    />
                    <ReferenceLine x={0} stroke="#94a3b8" />
                    <Bar dataKey="beta" radius={[0, 4, 4, 0]}>
                      {loadingsData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.beta > 0 ? "#2d7a4f" : "#8b2635"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Regression Table */}
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl flex flex-col shadow-sm overflow-hidden">
              <div className="p-6 border-b border-[var(--border-color)]">
                 <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--foreground)]">Regression Estimates</h3>
              </div>
              <div className="flex-1 overflow-x-auto p-4">
                <table className="w-full text-xs text-left">
                  <thead className="border-b border-[var(--border-color)]">
                    <tr>
                      <th className="px-4 py-2 font-medium text-brand-slate uppercase tracking-wider">Factor</th>
                      <th className="px-4 py-2 font-medium text-brand-slate uppercase tracking-wider text-right">Coefficient</th>
                      <th className="px-4 py-2 font-medium text-brand-slate uppercase tracking-wider text-right">Std Error</th>
                      <th className="px-4 py-2 font-medium text-brand-slate uppercase tracking-wider text-right">t-Stat</th>
                      <th className="px-4 py-2 font-medium text-brand-slate uppercase tracking-wider text-right">p-Value</th>
                      <th className="px-2 py-2 font-medium text-brand-slate uppercase tracking-wider">Sig</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-color)]">
                    {results.regression_table.map((row: any) => (
                      <tr key={row.factor} className="hover:bg-[var(--hover-bg)] transition-colors">
                        <td className="px-4 py-3 font-medium text-[var(--foreground)]">{row.factor}</td>
                        <td className="px-4 py-3 text-right font-mono">{row.beta}</td>
                        <td className="px-4 py-3 text-right font-mono text-brand-slate">{row.stderr}</td>
                        <td className="px-4 py-3 text-right font-mono">{row.t_stat}</td>
                        <td className="px-4 py-3 text-right font-mono text-brand-slate">{row.p_value}</td>
                        <td className="px-2 py-3 text-brand-gold font-bold">{row.significance}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            
            {/* Cumulative Fit */}
            <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
              <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--foreground)] border-b border-[var(--border-color)] pb-3 mb-6">
                Cumulative Performance vs Expected
              </h3>
              <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={results.cumulative_chart} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} opacity={0.5} />
                    <XAxis 
                      dataKey="date" 
                      stroke="var(--brand-slate)" 
                      fontSize={10} 
                      tickFormatter={(v) => v.substring(0, 7)}
                      minTickGap={30}
                    />
                    <YAxis stroke="var(--brand-slate)" fontSize={10} tickFormatter={(v) => `${(v*100).toFixed(0)}%`} />
                    <RechartsTooltip 
                      contentStyle={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border-color)', borderRadius: '8px' }}
                      itemStyle={{ fontSize: '12px' }}
                      labelStyle={{ color: 'var(--brand-slate)', fontSize: '10px', marginBottom: '4px' }}
                      formatter={(value: any) => [`${(Number(value)*100).toFixed(2)}%`]}
                    />
                    <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }}/>
                    <Line type="monotone" dataKey="actual" name="Actual Return" stroke="#cfa144" strokeWidth={2} dot={false} isAnimationActive={false} />
                    <Line type="monotone" dataKey="fitted" name="Explained (Factor Model)" stroke="#94a3b8" strokeWidth={2} dot={false} strokeDasharray="5 5" isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Rolling Drift */}
            {rollingResults.length > 0 && (
              <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-6 shadow-sm">
                <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--foreground)] border-b border-[var(--border-color)] pb-3 mb-6">
                  Style Drift (Rolling 60-Period Beta)
                </h3>
                <div className="h-[300px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={rollingResults} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} opacity={0.5} />
                      <XAxis 
                        dataKey="Date" 
                        stroke="var(--brand-slate)" 
                        fontSize={10} 
                        tickFormatter={(v) => v.substring(0, 7)}
                        minTickGap={30}
                      />
                      <YAxis stroke="var(--brand-slate)" fontSize={10} />
                      <RechartsTooltip 
                        contentStyle={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border-color)', borderRadius: '8px' }}
                        itemStyle={{ fontSize: '12px' }}
                        labelStyle={{ color: 'var(--brand-slate)', fontSize: '10px', marginBottom: '4px' }}
                      />
                      <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }}/>
                      
                      {Object.keys(rollingResults[0])
                        .filter(k => k !== "Date" && k !== "Alpha")
                        .map(factor => (
                          <Line 
                            key={factor}
                            type="monotone" 
                            dataKey={factor} 
                            name={factor} 
                            stroke={factorColors[factor] || "var(--brand-slate)"} 
                            strokeWidth={2} 
                            dot={false} 
                            isAnimationActive={false}
                          />
                        ))}
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
