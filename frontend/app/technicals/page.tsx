"use client";

import React, { useState, useEffect } from "react";
import { TickerSidebar } from "../../components/TickerSidebar";
import { AdvancedTechnicalChart } from "../../components/technicals/AdvancedTechnicalChart";
import { RiskMetricsChart } from "../../components/technicals/RiskMetricsChart";
import { ChevronsRight, Search } from "lucide-react";
import { MetricCard } from "../../components/screener/MetricCard";
import { useIsMobile } from "../../hooks/useIsMobile";

export default function TechnicalsPage() {
  const [selectedTicker, setSelectedTicker] = useState<string>("");
  const isMobile = useIsMobile();
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(!isMobile);
  const [account, setAccount] = useState<string>("Consolidated");
  
  const [data, setData] = useState<any>(null);
  const [info, setInfo] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [timeHorizon, setTimeHorizon] = useState<string>("1Y");
  
  const [aiReport, setAiReport] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState<boolean>(false);
  
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    document.title = "Technical Analysis | Aegis Terminal";
  }, []);

  // Update sidebar default based on mobile
  useEffect(() => {
    setIsSidebarOpen(!isMobile);
  }, [isMobile]);

  useEffect(() => {
    if (!selectedTicker) return;
    
    setLoading(true);
    setError(null);
    setData(null);
    setAiReport(null);

    fetch(`${API_URL}/api/screener/technicals?ticker=${selectedTicker}`)
      .then(async (res) => {
        if (!res.ok) {
          const e = await res.json();
          throw new Error(e.detail || "Failed to fetch technical data");
        }
        return res.json();
      })
      .then(d => {
        setData(d.timeseries);
        setInfo(d.info || {});
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, [selectedTicker]);

  const handleGenerateAI = async () => {
    if (!data || data.length === 0) return;
    setAiLoading(true);
    try {
      const latest = data[data.length - 1];
      const snapshot = `
Ticker: ${selectedTicker}
Date: ${latest.time}
Close Price: ${latest.close?.toFixed(2)}
RSI (14): ${latest.rsi?.toFixed(2)}
MACD: ${latest.macd?.toFixed(2)} (Signal: ${latest.macd_signal?.toFixed(2)})
SMA 50: ${latest.sma50?.toFixed(2)}
SMA 200: ${latest.sma200?.toFixed(2)}
Bollinger Upper: ${latest.bb_upper?.toFixed(2)}
Bollinger Lower: ${latest.bb_lower?.toFixed(2)}
30D Volatility: ${latest.volatility?.toFixed(2)}%
Current Drawdown: ${latest.drawdown?.toFixed(2)}%
      `.trim();

      const res = await fetch(`${API_URL}/api/screener/technicals-ai`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: selectedTicker,
          snapshot: snapshot
        })
      });
      
      if (!res.ok) {
        const e = await res.json();
        throw new Error(e.detail || "Generation failed");
      }
      
      const json = await res.json();
      setAiReport(json.report);
    } catch(err: any) {
      console.error(err);
      alert("Failed to generate AI report: " + err.message);
    } finally {
      setAiLoading(false);
    }
  };

  const getLatestMetrics = () => {
    if (!data || data.length === 0) return null;
    return data[data.length - 1];
  };

  const getFilteredData = () => {
    if (!data) return null;
    if (timeHorizon === "ALL") return data;
    
    const now = new Date();
    if (timeHorizon === "1W") now.setDate(now.getDate() - 7);
    else if (timeHorizon === "1M") now.setMonth(now.getMonth() - 1);
    else if (timeHorizon === "3M") now.setMonth(now.getMonth() - 3);
    else if (timeHorizon === "6M") now.setMonth(now.getMonth() - 6);
    else if (timeHorizon === "1Y") now.setFullYear(now.getFullYear() - 1);
    else if (timeHorizon === "5Y") now.setFullYear(now.getFullYear() - 5);
    
    const cutoffStr = now.toISOString().split("T")[0];
    return data.filter((d: any) => d.time >= cutoffStr);
  };

  const filteredData = getFilteredData();
  const latest = getLatestMetrics();

  return (
    <div className="flex flex-1 overflow-hidden h-[calc(100vh-64px)] w-full bg-[var(--background)] relative">
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
              Technical Analysis
            </h1>
            <p className="hidden md:block text-sm text-[var(--foreground)] max-w-xl font-light drop-shadow-sm">
              Advanced price action, momentum indicators, and volatility metrics.
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
          <div className="absolute inset-0 bg-[var(--background)]/50 backdrop-blur-sm z-10 flex items-center justify-center">
            <div className="text-[var(--foreground)] font-bold text-xl animate-pulse tracking-widest uppercase">Loading Charts...</div>
          </div>
        )}
        
        {error && (
          <div className="m-8 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-lg border border-red-200 dark:border-red-800">
            <h3 className="font-bold">Error Loading Data</h3>
            <p>{error}</p>
          </div>
        )}

        {data && !loading && (
          <div className="max-w-6xl mx-auto space-y-10 p-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            
            {/* Header Title */}
            <div className="pb-4 border-b border-[var(--border-color)]">
              <h1 className="text-3xl md:text-4xl font-serif text-[var(--foreground)] uppercase mb-1">
                {info?.longName || info?.shortName || selectedTicker} ({selectedTicker})
              </h1>
              <div className="text-3xl font-extrabold text-brand-gold tracking-tight font-sans">
                {info?.currency || "GBp"} {latest?.close?.toFixed(2)}
              </div>
            </div>

            {/* Header Section */}
            <div className="flex justify-between items-end">
              <div>
                <h2 className="font-serif text-2xl font-bold text-[var(--foreground)] mb-2">
                  Technical Indicators
                </h2>
                {latest && (
                  <div className="flex items-center gap-4 mt-2">
                    <span className="text-3xl font-extrabold text-brand-gold tracking-tight font-sans">
                      {latest.close?.toFixed(2)}
                    </span>
                    <span className={`text-sm font-semibold px-2 py-1 rounded-md ${latest.rsi > 70 ? 'bg-red-100 text-red-700' : latest.rsi < 30 ? 'bg-green-100 text-green-700' : 'bg-[var(--border-color)] text-brand-slate'}`}>
                      RSI: {latest.rsi?.toFixed(1)}
                    </span>
                    <span className={`text-sm font-semibold px-2 py-1 rounded-md ${latest.sma50 > latest.sma200 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                      {latest.sma50 > latest.sma200 ? 'UPTREND' : 'DOWNTREND'}
                    </span>
                  </div>
                )}
              </div>
              
              <div className="flex flex-col items-end gap-4">
                {/* Time Horizon Slider */}
                <div className="flex items-center gap-1 bg-[var(--foreground)]/5 p-1 rounded-lg border border-[var(--border-color)]">
                  {["1W", "1M", "3M", "6M", "1Y", "5Y", "ALL"].map((h) => (
                    <button
                      key={h}
                      onClick={() => setTimeHorizon(h)}
                      className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors ${
                        timeHorizon === h 
                          ? "bg-[var(--background)] text-brand-gold shadow-sm border border-[var(--border-color)]" 
                          : "text-[var(--foreground)]/60 hover:text-[var(--foreground)] hover:bg-[var(--foreground)]/5"
                      }`}
                    >
                      {h}
                    </button>
                  ))}
                </div>
                
                <button 
                  onClick={handleGenerateAI}
                  disabled={aiLoading}
                  className="bg-brand-gold hover:bg-yellow-600 text-white font-bold py-2 px-6 rounded-md shadow transition-colors disabled:opacity-50"
                >
                  {aiLoading ? "Generating Brief..." : "🤖 Generate AI Brief"}
                </button>
              </div>
            </div>

            {aiReport && (
              <section className="bg-brand-gold/10 border border-brand-gold/30 p-6 rounded-xl relative overflow-hidden">
                <div className="absolute top-0 left-0 w-1 h-full bg-brand-gold"></div>
                <h3 className="text-sm font-bold text-brand-gold uppercase tracking-widest mb-4">Technical Brief</h3>
                <div className="prose dark:prose-invert max-w-none text-sm text-[var(--foreground)]/90">
                  <div dangerouslySetInnerHTML={{ 
                    __html: aiReport
                      .replace(/\n/g, '<br/>')
                      .replace(/##\s(.*?)(?:<br\/>|$)/g, '<h4 class="text-brand-gold mt-4 mb-2">$1</h4>')
                      .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>') 
                  }} />
                </div>
              </section>
            )}

            {/* Key Indicators Grid */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <MetricCard 
                label="RSI (14)" 
                value={latest?.rsi?.toFixed(2)} 
                explanation="Relative Strength Index. >70 is overbought, <30 is oversold."
                valueColor={latest?.rsi > 70 ? "text-red-500" : latest?.rsi < 30 ? "text-green-500" : ""}
              />
              <MetricCard 
                label="MACD" 
                value={latest?.macd?.toFixed(3)} 
                subValue={`Signal: ${latest?.macd_signal?.toFixed(3)}`}
                explanation="Moving Average Convergence Divergence. Positive usually means upward momentum."
                valueColor={latest?.macd > latest?.macd_signal ? "text-green-500" : "text-red-500"}
              />
              <MetricCard 
                label="SMA 50 vs SMA 200" 
                value={latest?.sma50 > latest?.sma200 ? "Uptrend" : "Downtrend"} 
                subValue={`50D: ${latest?.sma50?.toFixed(2)} | 200D: ${latest?.sma200?.toFixed(2)}`}
                explanation="Short term moving average vs long term moving average trend indicator."
                valueColor={latest?.sma50 > latest?.sma200 ? "text-green-500" : "text-red-500"}
              />
              <MetricCard 
                label="30D Volatility" 
                value={`${latest?.volatility?.toFixed(2)}%`} 
                subValue={`Current DD: ${latest?.drawdown?.toFixed(2)}%`}
                explanation="Annualized rolling 30-day volatility and current drawdown from peak."
              />
            </div>

            {/* Advanced Charts */}
            <section>
              <h3 className="uppercase text-[10px] tracking-[0.2em] text-brand-slate font-semibold mb-4 border-b border-[var(--border-color)] pb-2">
                Price Action & Momentum
              </h3>
              <AdvancedTechnicalChart data={filteredData || data} />
            </section>

            {/* Risk Metrics */}
            <section>
              <h3 className="uppercase text-[10px] tracking-[0.2em] text-brand-slate font-semibold mb-4 border-b border-[var(--border-color)] pb-2 mt-10">
                Volatility & Risk
              </h3>
              <RiskMetricsChart data={filteredData || data} />
            </section>

          </div>
        )}
      </main>
    </div>
  );
}
