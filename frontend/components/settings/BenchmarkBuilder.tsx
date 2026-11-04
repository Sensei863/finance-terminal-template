"use client";

import React, { useState, useEffect } from "react";
import { Plus, X, Save, Trash2, LineChart as LineChartIcon, Activity } from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const EQUITY_PICKS = [
  { label: "S&P 500", ticker: "IUSA.L", ccy: "GBP" },
  { label: "MSCI World", ticker: "SWDA.L", ccy: "GBP" },
  { label: "Stoxx 600", ticker: "MEUD.L", ccy: "GBP" },
];

const FI_PICKS = [
  { label: "Global Agg", ticker: "AGGG.L", ccy: "GBP" },
  { label: "USD Corp", ticker: "SUCA.L", ccy: "USD" },
  { label: "EUR Govt", ticker: "ERNA.L", ccy: "EUR" },
  { label: "UK Gilts", ticker: "IGLA.L", ccy: "GBP" },
];

interface Constituent {
  ticker: string;
  currency: string;
  weight: number;
}

interface BenchmarkDef {
  name: string;
  constituents: Constituent[];
  rebalance_freq: string;
}

export function BenchmarkBuilder() {
  const [savedBenchmarks, setSavedBenchmarks] = useState<BenchmarkDef[]>([]);
  const [selectedLoad, setSelectedLoad] = useState<string>("");
  
  // Form State
  const [name, setName] = useState("");
  const [freq, setFreq] = useState("Q");
  const [rows, setRows] = useState<Constituent[]>([
    { ticker: "", currency: "GBP", weight: 1.0 },
  ]);

  // Preview State
  const [previewData, setPreviewData] = useState<any>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    fetchBenchmarks();
  }, []);

  const fetchBenchmarks = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/system/benchmarks`);
      const data = await res.json();
      setSavedBenchmarks(data.benchmarks || []);
    } catch (e) {
      console.error("Failed to fetch benchmarks", e);
    }
  };

  const loadBenchmark = (bName: string) => {
    const bm = savedBenchmarks.find((b) => b.name === bName);
    if (!bm) return;
    setName(bm.name);
    setFreq(bm.rebalance_freq);
    setRows(bm.constituents.map(c => ({ ...c })));
    fetchPreview(bm.name);
  };

  const fetchPreview = async (bName: string) => {
    setIsLoadingPreview(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/system/benchmarks/${encodeURIComponent(bName)}/performance?account=Consolidated`);
      if (res.ok) {
        const data = await res.json();
        setPreviewData(data);
      } else {
        setPreviewData(null);
      }
    } catch (e) {
      console.error(e);
      setPreviewData(null);
    }
    setIsLoadingPreview(false);
  };

  const deleteBenchmark = async () => {
    if (!selectedLoad) return;
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/system/benchmarks/${encodeURIComponent(selectedLoad)}`, { method: "DELETE" });
      setSavedBenchmarks(prev => prev.filter(b => b.name !== selectedLoad));
      setSelectedLoad("");
      if (name === selectedLoad) {
        setPreviewData(null);
      }
    } catch (e) {
      console.error("Delete failed", e);
    }
  };

  const handleRowChange = (index: number, field: keyof Constituent, value: string | number) => {
    const newRows = [...rows];
    newRows[index] = { ...newRows[index], [field]: value };
    setRows(newRows);
  };

  const removeRow = (index: number) => {
    setRows(rows.filter((_, i) => i !== index));
  };

  const addRow = (ticker = "", ccy = "GBP", weight = 0.0) => {
    setRows([...rows, { ticker, currency: ccy, weight }]);
  };

  const equaliseWeights = () => {
    const validRows = rows.filter(r => r.ticker.trim() !== "");
    if (validRows.length === 0) return;
    const eqW = parseFloat((1.0 / validRows.length).toFixed(4));
    setRows(rows.map(r => r.ticker.trim() !== "" ? { ...r, weight: eqW } : r));
  };

  const validRows = rows.filter(r => r.ticker.trim() !== "");
  const totalWeight = validRows.reduce((acc, r) => acc + r.weight, 0);
  const weightOk = Math.abs(totalWeight - 1.0) < 0.001;

  const saveBenchmark = async () => {
    if (!name.trim() || !weightOk || validRows.length === 0) return;
    setIsSaving(true);
    try {
      // 1. Save Definition
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/system/benchmarks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          constituents: validRows,
          rebalance_freq: freq
        })
      });
      
      // 2. Trigger Simulation
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/portfolio/recalculate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account: "Consolidated",
          force_full_prices: false,
          active_bm_name: name.trim()
        })
      });

      await fetchBenchmarks();
      await fetchPreview(name.trim());
      setSelectedLoad(name.trim());
    } catch (e) {
      console.error("Save failed", e);
    }
    setIsSaving(false);
  };

  return (
    <div className="flex flex-col gap-6">
      {/* HEADER */}
      <div>
        <h2 className="text-2xl font-serif text-brand-gold flex items-center gap-2">
          <Activity className="w-6 h-6" />
          Benchmark Builder
        </h2>
        <p className="text-brand-slate mt-1 max-w-2xl">
          Define custom multi-asset synthetic benchmarks. Save your definitions to run historical simulations and compare against your portfolios.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        {/* LEFT COLUMN: BUILDER */}
        <div className="xl:col-span-5 flex flex-col gap-6">
          {/* LOAD / DELETE */}
          <div className="bg-[var(--card-bg)] border border-[var(--border-color)] p-4 flex flex-col gap-4">
            <h3 className="text-sm uppercase tracking-widest text-brand-slate font-semibold">1. Load Saved Benchmark</h3>
            <div className="flex gap-2">
              <select
                className="flex-1 bg-[var(--background)] border border-[var(--border-color)] p-2 text-sm text-[var(--foreground)] outline-none focus:border-brand-gold transition-colors"
                value={selectedLoad}
                onChange={(e) => {
                  setSelectedLoad(e.target.value);
                  if (e.target.value) loadBenchmark(e.target.value);
                }}
              >
                <option value="">— Select Saved Benchmark —</option>
                {savedBenchmarks.map(b => (
                  <option key={b.name} value={b.name}>{b.name}</option>
                ))}
              </select>
              <button
                disabled={!selectedLoad}
                onClick={deleteBenchmark}
                className="p-2 border border-[var(--border-color)] hover:bg-red-500/10 hover:border-red-500/50 hover:text-red-400 transition-colors disabled:opacity-50"
                title="Delete Benchmark"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* BUILDER */}
          <div className="bg-[var(--card-bg)] border border-[var(--border-color)] p-4 flex flex-col gap-4">
            <h3 className="text-sm uppercase tracking-widest text-brand-slate font-semibold">2. Basket Composition</h3>
            
            {/* Quick Adds */}
            <div className="flex flex-col gap-2">
              <div className="flex gap-2 flex-wrap">
                {EQUITY_PICKS.map(p => (
                  <button
                    key={p.ticker}
                    onClick={() => addRow(p.ticker, p.ccy, 0)}
                    className="px-2 py-1 text-xs border border-[var(--border-color)] hover:border-brand-gold transition-colors flex items-center gap-1"
                  >
                    <Plus className="w-3 h-3" /> {p.label}
                  </button>
                ))}
              </div>
              <div className="flex gap-2 flex-wrap">
                {FI_PICKS.map(p => (
                  <button
                    key={p.ticker}
                    onClick={() => addRow(p.ticker, p.ccy, 0)}
                    className="px-2 py-1 text-xs border border-[var(--border-color)] hover:border-brand-gold transition-colors flex items-center gap-1"
                  >
                    <Plus className="w-3 h-3" /> {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Rows */}
            <div className="flex flex-col gap-2 mt-2">
              <div className="grid grid-cols-12 gap-2 text-[10px] uppercase tracking-widest text-brand-slate mb-1 px-1">
                <div className="col-span-5">Ticker</div>
                <div className="col-span-3">Ccy</div>
                <div className="col-span-3">Weight</div>
                <div className="col-span-1"></div>
              </div>
              {rows.map((row, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-center">
                  <input
                    type="text"
                    value={row.ticker}
                    placeholder="e.g. SWDA.L"
                    onChange={(e) => handleRowChange(i, "ticker", e.target.value.toUpperCase())}
                    className="col-span-5 bg-[var(--background)] border border-[var(--border-color)] px-2 py-1.5 text-sm font-mono outline-none focus:border-brand-gold transition-colors"
                  />
                  <select
                    value={row.currency}
                    onChange={(e) => handleRowChange(i, "currency", e.target.value)}
                    className="col-span-3 bg-[var(--background)] border border-[var(--border-color)] px-2 py-1.5 text-sm outline-none focus:border-brand-gold transition-colors"
                  >
                    <option value="GBP">GBP</option>
                    <option value="USD">USD</option>
                    <option value="EUR">EUR</option>
                  </select>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    value={row.weight}
                    onChange={(e) => handleRowChange(i, "weight", parseFloat(e.target.value) || 0)}
                    className="col-span-3 bg-[var(--background)] border border-[var(--border-color)] px-2 py-1.5 text-sm font-mono outline-none focus:border-brand-gold transition-colors"
                  />
                  <button onClick={() => removeRow(i)} className="col-span-1 p-1.5 text-brand-slate hover:text-red-400 transition-colors flex justify-center">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>

            {/* Row Controls */}
            <div className="flex items-center justify-between mt-2 pt-4 border-t border-[var(--border-color)]">
              <div className="flex gap-2">
                <button onClick={() => addRow()} className="text-xs font-semibold px-3 py-1.5 border border-[var(--border-color)] hover:border-brand-gold transition-colors flex items-center gap-1">
                  <Plus className="w-3 h-3" /> Add Row
                </button>
                <button onClick={equaliseWeights} className="text-xs font-semibold px-3 py-1.5 border border-[var(--border-color)] hover:border-brand-gold transition-colors flex items-center gap-1">
                  Equalise
                </button>
              </div>
              <div className={`text-sm font-mono font-bold ${weightOk ? 'text-brand-green' : 'text-red-400'}`}>
                {(totalWeight * 100).toFixed(0)}%
              </div>
            </div>
          </div>

          {/* SAVE */}
          <div className="bg-[var(--card-bg)] border border-[var(--border-color)] p-4 flex flex-col gap-4">
            <h3 className="text-sm uppercase tracking-widest text-brand-slate font-semibold">3. Save & Simulate</h3>
            <div className="flex flex-col gap-3">
              <div>
                <label className="text-[10px] uppercase tracking-widest text-brand-slate mb-1 block">Benchmark Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. My 60/40"
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] px-3 py-2 text-sm outline-none focus:border-brand-gold transition-colors"
                />
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-widest text-brand-slate mb-1 block">Rebalance Frequency</label>
                <select
                  value={freq}
                  onChange={(e) => setFreq(e.target.value)}
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] px-3 py-2 text-sm outline-none focus:border-brand-gold transition-colors"
                >
                  <option value="Q">Quarterly</option>
                  <option value="SA">Semi-Annual</option>
                  <option value="A">Annual</option>
                  <option value="None">Buy & Hold</option>
                </select>
              </div>
              <button
                disabled={!name.trim() || !weightOk || validRows.length === 0 || isSaving}
                onClick={saveBenchmark}
                className="mt-2 w-full flex items-center justify-center gap-2 bg-brand-gold hover:bg-brand-gold-light text-[var(--background)] font-bold py-2 px-4 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSaving ? (
                  <div className="w-5 h-5 border-2 border-[var(--background)] border-t-transparent rounded-full animate-spin" />
                ) : (
                  <>
                    <Save className="w-4 h-4" /> Save & Simulate
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: PREVIEW */}
        <div className="xl:col-span-7 flex flex-col gap-6">
          <div className="bg-[var(--card-bg)] border border-[var(--border-color)] p-6 min-h-[500px] flex flex-col h-full">
            <h3 className="text-sm uppercase tracking-widest text-brand-slate font-semibold mb-6 flex items-center gap-2">
              <LineChartIcon className="w-4 h-4" /> Performance Preview
            </h3>

            {isLoadingPreview ? (
              <div className="flex-1 flex flex-col items-center justify-center gap-4 text-brand-slate">
                <div className="w-8 h-8 border-2 border-brand-gold border-t-transparent rounded-full animate-spin" />
                <p className="text-sm animate-pulse">Running simulation...</p>
              </div>
            ) : previewData ? (
              <div className="flex flex-col h-full gap-6">
                <div className="h-[350px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={previewData.chart_data}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-color)" opacity={0.5} />
                      <XAxis 
                        dataKey="date" 
                        stroke="var(--border-color)" 
                        tick={{ fill: "var(--foreground)", fontSize: 10, opacity: 0.7 }}
                        tickFormatter={(val) => {
                          const d = new Date(val);
                          return `${d.toLocaleString('default', { month: 'short' })} ${d.getFullYear()}`;
                        }}
                        minTickGap={30}
                      />
                      <YAxis 
                        stroke="var(--border-color)" 
                        tick={{ fill: "var(--foreground)", fontSize: 10, opacity: 0.7 }}
                        domain={['auto', 'auto']}
                        tickFormatter={(val) => val.toFixed(0)}
                        width={40}
                      />
                      <Tooltip 
                        contentStyle={{ backgroundColor: 'var(--background)', borderColor: 'var(--border-color)', borderRadius: '0px' }}
                        itemStyle={{ color: 'var(--foreground)' }}
                        labelStyle={{ color: 'var(--brand-gold)', marginBottom: '4px' }}
                      />
                      <Line 
                        type="monotone" 
                        dataKey="TWR_Index" 
                        stroke="#0ea5e9" 
                        strokeWidth={2} 
                        dot={false}
                        isAnimationActive={false}
                        name={name || selectedLoad || "Benchmark"}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-auto">
                  <div className="border border-[var(--border-color)] p-3 flex flex-col items-center justify-center">
                    <span className="text-[10px] uppercase tracking-widest text-brand-slate mb-1">Total Return</span>
                    <span className="font-mono text-lg font-bold text-brand-green">
                      {(previewData.metrics.total_return * 100).toFixed(2)}%
                    </span>
                  </div>
                  <div className="border border-[var(--border-color)] p-3 flex flex-col items-center justify-center">
                    <span className="text-[10px] uppercase tracking-widest text-brand-slate mb-1">CAGR</span>
                    <span className="font-mono text-lg font-bold text-brand-green">
                      {(previewData.metrics.cagr * 100).toFixed(2)}%
                    </span>
                  </div>
                  <div className="border border-[var(--border-color)] p-3 flex flex-col items-center justify-center">
                    <span className="text-[10px] uppercase tracking-widest text-brand-slate mb-1">Volatility</span>
                    <span className="font-mono text-lg font-bold">
                      {(previewData.metrics.ann_vol * 100).toFixed(2)}%
                    </span>
                  </div>
                  <div className="border border-[var(--border-color)] p-3 flex flex-col items-center justify-center">
                    <span className="text-[10px] uppercase tracking-widest text-brand-slate mb-1">Max DD</span>
                    <span className="font-mono text-lg font-bold text-red-400">
                      {(previewData.metrics.max_dd * 100).toFixed(2)}%
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-center text-brand-slate opacity-50 px-8">
                <Activity className="w-12 h-12 mb-4" />
                <p>No preview data available. Select a saved benchmark or build a new one and click 'Save & Simulate' to generate performance metrics.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
