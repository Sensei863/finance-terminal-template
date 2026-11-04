"use client";

import React, { useState, useEffect } from "react";
import { Search, Activity, TrendingUp, AlertTriangle, ChevronsRight } from "lucide-react";
import { MetricCard } from "../../components/screener/MetricCard";
import { TrendScanner } from "../../components/screener/TrendScanner";
import { PerformanceChart } from "../../components/screener/PerformanceChart";
import { AIReportPanel } from "../../components/screener/AIReportPanel";
import { ActivityTable } from "../../components/screener/ActivityTable";

import { TickerSidebar } from "../../components/TickerSidebar";
import { useIsMobile } from "../../hooks/useIsMobile";

const formatDate = (dateStr: string | null | undefined) => {
  if (!dateStr) return "N/A";
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return dateStr;
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
};

const calculateHoldingPeriod = (startStr: string | null | undefined, endStr: string | null | undefined) => {
  if (!startStr || !endStr) return "N/A";
  const start = new Date(startStr);
  const end = new Date(endStr);
  const diffTime = end.getTime() - start.getTime();
  if (isNaN(diffTime) || diffTime < 0) return "N/A";
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "1 day";
  if (diffDays < 30) return `${diffDays} days`;
  if (diffDays < 365) {
    const months = (diffDays / 30.4375).toFixed(1);
    return `${months} months`;
  }
  const years = (diffDays / 365.25).toFixed(1);
  return `${years} years (${diffDays} days)`;
};

export default function PerformancePage() {
  const [selectedTicker, setSelectedTicker] = useState<string>("");
  const [benchmark, setBenchmark] = useState<string>("IUSA.L");
  const [account, setAccount] = useState<string>("Consolidated");
  const [chartHorizon, setChartHorizon] = useState<string>("1Y");
  const isMobile = useIsMobile();
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(!isMobile);
  
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    document.title = "Performance & PnL | Aegis Terminal";
  }, []);

  // Update sidebar default based on mobile
  useEffect(() => {
    setIsSidebarOpen(!isMobile);
  }, [isMobile]);

  // Tickers are now managed inside the TickerSidebar component.

  useEffect(() => {
    if (!selectedTicker) return;
    
    setLoading(true);
    setError(null);
    setData(null);

    fetch(`${API_URL}/api/screener/data?ticker=${selectedTicker}&benchmark=${benchmark}&account=${account}`)
      .then(async (res) => {
        if (!res.ok) {
          const e = await res.json();
          throw new Error(e.detail || "Failed to fetch data");
        }
        return res.json();
      })
      .then(d => {
        setData(d);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [selectedTicker, benchmark, account]);

  const handleGenerateAI = async (type: "ai-analysis" | "market-intel") => {
    if (!data) throw new Error("No data loaded");
    
    const res = await fetch(`${API_URL}/api/screener/${type}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: selectedTicker,
        info: data.info,
        metrics: data.metrics
      })
    });
    
    if (!res.ok) {
      const e = await res.json();
      throw new Error(e.detail || "Generation failed");
    }
    
    const json = await res.json();
    return json.report;
  };

  const currency = data?.info?.currency || "USD";

  const getFilteredChartData = () => {
    if (!data?.chart_data) return [];
    const allData = data.chart_data;
    if (chartHorizon === "ALL") return allData;
    
    const now = new Date(allData[allData.length - 1].date);
    let cutoffDate = new Date(now);
    
    switch(chartHorizon) {
      case "1W": cutoffDate.setDate(cutoffDate.getDate() - 7); break;
      case "1M": cutoffDate.setMonth(cutoffDate.getMonth() - 1); break;
      case "3M": cutoffDate.setMonth(cutoffDate.getMonth() - 3); break;
      case "6M": cutoffDate.setMonth(cutoffDate.getMonth() - 6); break;
      case "1Y": cutoffDate.setFullYear(cutoffDate.getFullYear() - 1); break;
      case "3Y": cutoffDate.setFullYear(cutoffDate.getFullYear() - 3); break;
      case "5Y": cutoffDate.setFullYear(cutoffDate.getFullYear() - 5); break;
      case "Since First Buy": 
        if (data.portfolio?.metrics?.first_buy_date) {
          cutoffDate = new Date(data.portfolio.metrics.first_buy_date);
        }
        break;
    }
    
    const filtered = allData.filter((d: any) => new Date(d.date) >= cutoffDate);
    if (filtered.length === 0) return [];
    
    const base_asset_pct = filtered[0].asset_pct || 0;
    const base_bench_pct = filtered[0].bench_pct || 0;
    const base_port_pct = filtered[0].port_pct || 0;
    
    return filtered.map((d: any) => ({
      ...d,
      asset_pct: d.asset_pct !== null ? (((d.asset_pct/100 + 1) / (base_asset_pct/100 + 1) - 1) * 100) : null,
      bench_pct: d.bench_pct != null ? (((d.bench_pct/100 + 1) / (base_bench_pct/100 + 1) - 1) * 100) : null,
      port_pct: d.port_pct != null ? (((d.port_pct/100 + 1) / (base_port_pct/100 + 1) - 1) * 100) : null,
    }));
  };

  return (
    <div className="flex h-[calc(100vh-64px)] w-full overflow-hidden">
      
      <TickerSidebar 
        isOpen={isSidebarOpen} 
        onToggle={() => setIsSidebarOpen(!isSidebarOpen)} 
        selectedTicker={selectedTicker} 
        onSelectTicker={setSelectedTicker} 
        selectedAccount={account}
        onSelectAccount={setAccount}
      />

      {/* ══ DASHBOARD CONTENT ══ */}
      <main className="flex-1 overflow-auto bg-[var(--background)] relative w-full">
        {/* Desktop Sidebar Toggle */}
        {!isSidebarOpen && !isMobile && (
          <button 
            onClick={() => setIsSidebarOpen(true)}
            className="hidden md:flex absolute left-4 top-4 p-2 bg-[var(--background)]/50 backdrop-blur-sm border border-[var(--border-color)] rounded-md shadow-sm hover:border-brand-gold transition-colors z-20"
            title="Open Sidebar"
          >
            <ChevronsRight className="w-4 h-4 text-[var(--foreground)]/70" />
          </button>
        )}
        
        {/* Mobile FAB for TickerSidebar */}
        {isMobile && (
          <button 
            onClick={() => setIsSidebarOpen(true)}
            className="md:hidden fixed bottom-6 right-6 p-4 bg-brand-gold text-[var(--background)] rounded-full shadow-xl hover:bg-brand-gold-light transition-colors z-30"
            title="Select Asset"
          >
            <Search className="w-5 h-5" />
          </button>
        )}
        
        {/* HERO BANNER */}
        <div className="w-full h-[120px] md:h-[200px] border-y-[3px] border-brand-gold relative flex justify-end bg-[var(--background)] shrink-0">
          <div className="absolute left-4 md:left-16 bottom-4 md:bottom-8 z-10 pointer-events-none max-w-2xl">
            <h1 className="text-3xl md:text-5xl font-serif text-brand-gold mb-1 md:mb-2 drop-shadow-md tracking-tight">
              Performance & PnL
            </h1>
            <p className="hidden md:block text-sm text-[var(--foreground)] max-w-xl font-light drop-shadow-sm">
              Deep dive into historical returns, dividend yield, and current position metrics.
            </p>
          </div>
          <div className="relative w-full max-w-[800px] h-full">
            <img 
              src="/hero.png" 
              alt="Generated Coastal Scene" 
              className="w-full h-full object-cover object-[right_55%]"
            />
            <div className="absolute inset-0 bg-gradient-to-r from-[var(--background)] via-[var(--background)]/60 to-transparent pointer-events-none"></div>
          </div>
        </div>

        {loading && (
          <div className="absolute inset-0 bg-white/50 dark:bg-brand-navy/50 backdrop-blur-sm z-10 flex items-center justify-center">
            <div className="text-[var(--foreground)] font-bold text-xl animate-pulse tracking-widest uppercase">Loading Data...</div>
          </div>
        )}
        
        {error && (
          <div className="m-8 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-lg border border-red-200 dark:border-red-800">
            <h3 className="font-bold">Error Loading Data</h3>
            <p>{error}</p>
          </div>
        )}

        {data && !loading && (
          <div className="max-w-5xl mx-auto space-y-10 p-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            
            {/* Header Title */}
            <div className="pb-4 border-b border-[var(--border-color)]">
              <h1 className="text-3xl md:text-4xl font-serif text-[var(--foreground)] uppercase mb-1">
                {data.info.longName || data.info.shortName || selectedTicker} ({selectedTicker})
              </h1>
              <div className="text-3xl font-extrabold text-brand-gold tracking-tight font-sans">
                {currency} {data.metrics.Price?.toFixed(2)}
              </div>
            </div>

            {/* Portfolio Integration */}
            <section>
              <h3 className="uppercase text-[10px] tracking-[0.2em] text-brand-slate font-semibold mb-4 border-b border-[var(--border-color)] pb-2">💼 Portfolio Integration</h3>
              
              {data.portfolio.metrics.total_shares <= 0.001 ? (
                data.portfolio.metrics.first_buy_date === null ? (
                  <div className="bg-blue-50 dark:bg-blue-900/20 text-blue-800 dark:text-blue-300 p-4 rounded-lg border border-[var(--border-color)]">
                    You do not currently hold and have never traded {selectedTicker}.
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="bg-blue-50 dark:bg-blue-900/20 text-blue-800 dark:text-blue-300 p-4 rounded-lg border border-[var(--border-color)]">
                      You previously held {selectedTicker} but it is currently fully exited.
                    </div>
                    
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
                      <MetricCard 
                        label="Holding Period" 
                        value={calculateHoldingPeriod(data.portfolio.metrics.first_buy_date, data.portfolio.metrics.last_trade_date)}
                        subValue={`From ${formatDate(data.portfolio.metrics.first_buy_date)} to ${formatDate(data.portfolio.metrics.last_trade_date)}`}
                        explanation="The timeline between your first purchase and your final exit trade."
                      />
                      <MetricCard 
                        label="Total Purchases" 
                        value={`${currency} ${data.portfolio.metrics.total_purchases?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                        explanation="Total cash spent buying this asset."
                      />
                      <MetricCard 
                        label="Total Sales" 
                        value={`${currency} ${data.portfolio.metrics.total_sales?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                        explanation="Total cash received from selling this asset."
                      />
                      <MetricCard 
                        label="Realised P/L" 
                        value={`${currency} ${data.portfolio.metrics.realised_profit?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                        valueColor={data.portfolio.metrics.realised_profit >= 0 ? "text-brand-green" : "text-brand-red"}
                        explanation="Cash profit locked in from selling shares (Total Sales - Cost of Shares Sold). Excludes dividends."
                      />
                    </div>
                    
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                      <MetricCard 
                        label="Total Dividends" 
                        value={`${currency} ${data.portfolio.metrics.total_dividends?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                        explanation="Total dividends received across the holding period."
                      />
                      <MetricCard 
                        label="Cumulative P/L" 
                        value={`${currency} ${data.portfolio.metrics.lifetime_profit?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                        valueColor={data.portfolio.metrics.lifetime_profit >= 0 ? "text-brand-green" : "text-brand-red"}
                        explanation="Realised P/L + Total Dividends Received."
                      />
                      <MetricCard 
                        label="Total Return" 
                        value={`${(data.portfolio.metrics.abs_return * 100)?.toFixed(2)}%`}
                        valueColor={data.portfolio.metrics.abs_return >= 0 ? "text-brand-green" : "text-brand-red"}
                        explanation="Cumulative P/L divided by Total Purchases."
                      />
                      <MetricCard 
                        label="Ann. Return (CAGR)" 
                        value={`${(data.portfolio.metrics.ann_return * 100)?.toFixed(2)}%`}
                        valueColor={data.portfolio.metrics.ann_return >= 0 ? "text-brand-green" : "text-brand-red"}
                        explanation="Compound Annual Growth Rate over the holding period."
                      />
                    </div>
                  </div>
                )
              ) : (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
                    <MetricCard 
                      label="Current Holdings" 
                      value={`${data.portfolio.metrics.total_shares?.toFixed(4)} Shares`}
                      subValue={Object.entries(data.portfolio.breakdown).map(([k, v]) => `${k}: ${(v as number).toFixed(4)}`).join(' • ')}
                      explanation="Total number of shares currently held across all linked accounts."
                    />
                    <MetricCard 
                      label="Current Valuation" 
                      value={`${currency} ${(data.portfolio.metrics.total_shares * data.metrics.Price)?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                      explanation="Current market value of your holdings (Shares × Current Price)."
                    />
                    <MetricCard 
                      label="Avg Book Cost" 
                      value={data.portfolio.metrics.avg_book_cost > 0 ? `${currency} ${data.portfolio.metrics.avg_book_cost?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : "N/A"}
                      explanation="The average price paid for the shares you currently hold."
                    />
                    <MetricCard 
                      label="Net Cash Invested" 
                      value={`${currency} ${data.portfolio.metrics.net_cash_invested?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                      explanation="Total Cash Paid (Buys) minus Total Cash Received (Sells)."
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <MetricCard 
                      label="Realised P/L" 
                      value={`${currency} ${data.portfolio.metrics.realised_profit?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                      valueColor={data.portfolio.metrics.realised_profit >= 0 ? "text-brand-green" : "text-brand-red"}
                      explanation="Cash profit locked in from selling shares (Total Sales - Cost of Shares Sold). Excludes dividends."
                    />
                    <MetricCard 
                      label="Unrealised P/L" 
                      value={`${currency} ${data.portfolio.metrics.unrealised_profit?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                      valueColor={data.portfolio.metrics.unrealised_profit >= 0 ? "text-brand-green" : "text-brand-red"}
                      explanation="Paper profit of currently held shares (Current Valuation - Cost Basis)."
                    />
                    <MetricCard 
                      label="Cumulative P/L" 
                      value={`${currency} ${data.portfolio.metrics.lifetime_profit?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                      valueColor={data.portfolio.metrics.lifetime_profit >= 0 ? "text-brand-green" : "text-brand-red"}
                      explanation="Realised P/L + Unrealised P/L + Total Dividends Received."
                    />
                    <MetricCard 
                      label="Total Return" 
                      value={`${(data.portfolio.metrics.abs_return * 100)?.toFixed(2)}%`}
                      valueColor={data.portfolio.metrics.abs_return >= 0 ? "text-brand-green" : "text-brand-red"}
                      explanation="Cumulative P/L divided by Total Purchases."
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-4">
                    <MetricCard 
                      label="Total Dividends" 
                      value={`${currency} ${data.portfolio.metrics.total_dividends?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`}
                      explanation="Total dividends received across the holding period."
                    />
                    <MetricCard 
                      label="TTM Yield" 
                      value={`${(data.portfolio.metrics.ttm_yield * 100)?.toFixed(2)}%`}
                      explanation="Trailing Twelve Months dividend yield based on current price."
                    />
                    <MetricCard 
                      label="Yield on Cost" 
                      value={`${(data.portfolio.metrics.yield_on_cost * 100)?.toFixed(2)}%`}
                      explanation="Yield based on your average book cost."
                    />
                    <MetricCard 
                      label="Ann. Return (CAGR)" 
                      value={`${(data.portfolio.metrics.ann_return * 100)?.toFixed(2)}%`}
                      valueColor={data.portfolio.metrics.ann_return >= 0 ? "text-brand-green" : "text-brand-red"}
                      explanation="Compound Annual Growth Rate over the holding period."
                    />
                  </div>
                </>
              )}
            </section>

            {/* Activity History */}
            <ActivityTable 
              trades={data.trades} 
              dividends={data.dividends} 
              currency={currency} 
              currentPrice={data.metrics.Price}
            />

            {/* Trend & Momentum Scanner */}
            <section>
              <h3 className="uppercase text-[10px] tracking-[0.2em] text-brand-slate font-semibold mb-4 border-b border-[var(--border-color)] pb-2">📈 Trend Regime & Momentum Scanner</h3>
              <TrendScanner 
                trend={data.metrics.Trend}
                sma50={data.metrics.SMA50}
                sma200={data.metrics.SMA200}
                distSma50={data.metrics.DistSMA50}
                distSma200={data.metrics.DistSMA200}
                rsi={data.metrics.RSI}
                bbPos={data.metrics.BB_Pos}
                bbUpper={data.metrics.BB_Upper}
                bbLower={data.metrics.BB_Lower}
                macd={data.metrics.MACD}
                macdSignal={data.metrics.MACD_Signal}
                macdHist={data.metrics.MACD_Hist}
              />
            </section>

            {/* Performance Chart */}
            <section>
              <div className="flex items-center justify-between mb-4 border-b border-[var(--border-color)] pb-2">
                <h3 className="uppercase text-[10px] tracking-[0.2em] text-brand-slate font-semibold">Performance Chart</h3>
                
                {/* Time Horizon Slider / Buttons */}
                <div className="flex flex-wrap items-center bg-[var(--border-color)]/30 rounded-md p-0.5 gap-0.5">
                  {['1W', '1M', '3M', '6M', '1Y', '3Y', '5Y', 'ALL', 'Since First Buy'].map(hz => (
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

              <div className="bg-[var(--background)] p-4 rounded-xl border border-[var(--border-color)] shadow-sm">
                <PerformanceChart 
                  data={getFilteredChartData()} 
                  trades={data.trades} 
                  dividends={data.dividends} 
                  ticker={selectedTicker} 
                  benchmark={benchmark} 
                />
              </div>
            </section>

            {/* AI Reports */}
            <div className="flex flex-col gap-8">
              <AIReportPanel 
                ticker={selectedTicker} 
                type="market-intel" 
                onGenerate={() => handleGenerateAI("market-intel")} 
              />
              <AIReportPanel 
                ticker={selectedTicker} 
                type="qualitative" 
                onGenerate={() => handleGenerateAI("ai-analysis")} 
              />
            </div>

            {/* Bottom Metrics */}
            <section className="grid grid-cols-2 md:grid-cols-5 gap-4">
              {[
                { l: "1 Week", v: data.metrics["1W"] },
                { l: "1 Month", v: data.metrics["1M"] },
                { l: "3 Months", v: data.metrics["3M"] },
                { l: "6 Months", v: data.metrics["6M"] },
                { l: "1 Year", v: data.metrics["1Y"] },
              ].map((m, i) => (
                <div key={i} className="bg-[var(--background)] p-4 rounded-lg border border-[var(--border-color)] text-center shadow-sm">
                  <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-1">{m.l}</div>
                  <div className={`text-xl font-bold font-sans ${m.v === null ? "text-gray-500" : m.v >= 0 ? "text-brand-green" : "text-brand-red"}`}>
                    {m.v === null ? "N/A" : `${m.v >= 0 ? "+" : ""}${(m.v * 100).toFixed(2)}%`}
                  </div>
                </div>
              ))}
            </section>

          </div>
        )}
      </main>
    </div>
  );
}
