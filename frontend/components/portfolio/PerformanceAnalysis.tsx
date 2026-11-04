"use client";

import React, { useEffect, useState } from "react";
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer 
} from "recharts";
import { 
  TrendingUp, 
  ArrowUpRight, 
  ArrowDownRight, 
  Calendar, 
  Info, 
  RefreshCw, 
  FileText 
} from "lucide-react";

interface PerformanceAnalysisProps {
  account: string;
}

const InfoTooltip = ({ text }: { text: string }) => {
  return (
    <div className="relative group inline-block ml-1.5 align-middle">
      <Info className="w-3.5 h-3.5 text-brand-slate cursor-help hover:text-brand-gold transition-colors" />
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block w-48 bg-[#0a1628] border border-[#c9a84c]/30 text-[#f8f5ef] text-[10px] p-2 rounded shadow-lg z-50 pointer-events-none text-center font-sans font-normal normal-case leading-normal whitespace-normal">
        {text}
        <div className="absolute top-full left-1/2 -translate-x-1/2 w-2 h-2 bg-[#0a1628] border-r border-b border-[#c9a84c]/30 rotate-45 -mt-1"></div>
      </div>
    </div>
  );
};

export function PerformanceAnalysis({ account }: PerformanceAnalysisProps) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  
  const [horizon, setHorizon] = useState("1Y");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  
  const [activeTab, setActiveTab] = useState<"summary" | "detail">("summary");
  
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  // Fetch report data
  const fetchReport = () => {
    if (!account) return;
    setLoading(true);
    setError("");
    
    let url = `${API_URL}/api/portfolio/performance-report?account=${encodeURIComponent(account)}&horizon=${horizon}`;
    if (startDate) {
      url += `&start_date=${startDate}`;
    }
    if (endDate) {
      url += `&end_date=${endDate}`;
    }
    
    fetch(url)
      .then(res => {
        if (!res.ok) throw new Error("Failed to load performance report data");
        return res.json();
      })
      .then(d => {
        setData(d);
        // Sync custom date picker fields if they are empty
        if (!startDate && d.date_start) {
          setStartDate(d.date_start);
        }
        if (!endDate && d.date_end) {
          setEndDate(d.date_end);
        }
        setLoading(false);
      })
      .catch(e => {
        setError(e.message);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchReport();
  }, [account, horizon]);

  const handleCustomDateApply = (e: React.FormEvent) => {
    e.preventDefault();
    fetchReport();
  };

  const handleResetDates = () => {
    setStartDate("");
    setEndDate("");
    setHorizon("1Y");
  };

  if (loading) {
    return <div className="p-8 text-[var(--foreground)] animate-pulse font-serif tracking-widest uppercase">Generating Report...</div>;
  }

  if (error) {
    return <div className="p-8 text-brand-red border border-brand-red/20 bg-brand-red/5">{error}</div>;
  }

  if (!data) return null;

  const { base_currency, currency_symbol, value_start, value_end, increase, twr_return_pct, payments_transfers, performance, chart_data } = data;
  const isIncreasePos = increase >= 0;
  const isTwrPos = twr_return_pct >= 0;

  // Custom Recharts Tooltip
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-[var(--background)] border border-[var(--border-color)] p-4 shadow-xl text-xs rounded">
          <p className="text-brand-slate font-medium mb-1">{label}</p>
          <p className="text-brand-gold font-bold">
            NAV: {currency_symbol}{payload[0].value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </p>
          {payload[1] && (
            <p className="text-brand-slate mt-1 font-mono">
              TWR Index: {payload[1].value?.toFixed(2)}
            </p>
          )}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      
      {/* ══ HERO CARD OVERVIEW ══ */}
      <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
        <div>
          <div className="text-[10px] uppercase tracking-[0.2em] text-brand-slate font-bold mb-1">Account Portfolio</div>
          <h2 className="text-2xl font-serif text-brand-gold font-semibold uppercase">{account}</h2>
          <div className="text-[10px] text-brand-slate mt-1 font-mono uppercase">
            Period: {data.date_start} to {data.date_end}
          </div>
        </div>
        
        <div className="flex gap-8 items-center border-t md:border-t-0 pt-4 md:pt-0 border-[var(--border-color)] w-full md:w-auto">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-1">Total Valuation</div>
            <div className="text-3xl font-serif font-semibold text-[var(--foreground)]">
              {currency_symbol}{value_end.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-widest text-brand-slate font-semibold mb-1">TWR Change</div>
            <div className={`text-3xl font-serif font-bold flex items-center justify-end gap-1 ${isTwrPos ? "text-brand-green" : "text-brand-red"}`}>
              {isTwrPos ? <ArrowUpRight className="w-5 h-5" /> : <ArrowDownRight className="w-5 h-5" />}
              {isTwrPos ? "+" : ""}{twr_return_pct.toFixed(2)}%
            </div>
          </div>
        </div>
      </div>

      {/* ══ TIMELINE HORIZON & DATE SELECTORS ══ */}
      <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          
          {/* Horizon Sliders */}
          <div>
            <span className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider mb-2">Time Horizon</span>
            <div className="flex flex-wrap items-center bg-[var(--border-color)]/30 rounded-md p-0.5 gap-0.5">
              {['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'MAX'].map(hz => (
                <button
                  key={hz}
                  onClick={() => {
                    setHorizon(hz);
                    // Clear custom pickers to let horizon decide
                    setStartDate("");
                    setEndDate("");
                  }}
                  className={`px-3 py-1 text-[10px] font-semibold tracking-wider transition-colors rounded-sm ${
                    horizon === hz && !startDate
                      ? "bg-[var(--background)] text-[var(--foreground)] shadow-sm border border-[var(--border-color)]" 
                      : "text-brand-slate hover:text-[var(--foreground)]"
                  }`}
                >
                  {hz}
                </button>
              ))}
            </div>
          </div>
          
          {/* Custom Date Form */}
          <form onSubmit={handleCustomDateApply} className="flex flex-wrap items-end gap-4 w-full md:w-auto">
            <div>
              <label className="block text-[10px] font-semibold text-brand-slate uppercase tracking-wider mb-1 flex items-center gap-1">
                <Calendar className="w-3 h-3 text-brand-gold" /> From Date
              </label>
              <input 
                type="date" 
                value={startDate} 
                onChange={e => setStartDate(e.target.value)}
                className="bg-[var(--background)] border border-[var(--border-color)] text-xs text-brand-slate p-1.5 rounded outline-none focus:border-brand-gold font-sans w-36"
              />
            </div>
            <div>
              <label className="block text-[10px] font-semibold text-brand-slate uppercase tracking-wider mb-1 flex items-center gap-1">
                <Calendar className="w-3 h-3 text-brand-gold" /> To Date
              </label>
              <input 
                type="date" 
                value={endDate} 
                onChange={e => setEndDate(e.target.value)}
                className="bg-[var(--background)] border border-[var(--border-color)] text-xs text-brand-slate p-1.5 rounded outline-none focus:border-brand-gold font-sans w-36"
              />
            </div>
            <div className="flex gap-2">
              <button 
                type="submit"
                className="px-4 py-2 bg-brand-navy-light text-white hover:bg-brand-gold text-xs font-semibold uppercase tracking-wider transition-colors rounded"
              >
                Apply
              </button>
              {(startDate || endDate) && (
                <button 
                  type="button" 
                  onClick={handleResetDates}
                  className="p-2 border border-[var(--border-color)] hover:border-brand-red text-brand-slate hover:text-brand-red rounded transition-colors"
                  title="Reset Dates"
                >
                  <RefreshCw className="w-3 h-3" />
                </button>
              )}
            </div>
          </form>
          
        </div>
      </div>

      {/* ══ NAV TIMELINE VALUATION CHART ══ */}
      <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm">
        <h3 className="text-md font-serif text-brand-gold mb-4 flex items-center gap-2">
          <TrendingUp className="w-4 h-4" /> Valuation Trend ({currency_symbol})
        </h3>
        <div className="h-[250px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chart_data} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
              <defs>
                <linearGradient id="colorNav" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#cfa144" stopOpacity={0.2}/>
                  <stop offset="95%" stopColor="#cfa144" stopOpacity={0.01}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
              <XAxis 
                dataKey="time" 
                type="number"
                scale="time"
                domain={['dataMin', 'dataMax']}
                stroke="var(--foreground)" 
                fontSize={10}
                tickFormatter={(val) => {
                  if (!val) return "";
                  const d = new Date(val);
                  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
                }}
              />
              <YAxis 
                stroke="var(--foreground)" 
                fontSize={10}
                domain={['auto', 'auto']}
                tickFormatter={(val) => `${currency_symbol}${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area 
                type="monotone" 
                dataKey="Total_NAV" 
                stroke="#cfa144" 
                strokeWidth={2}
                fillOpacity={1} 
                fill="url(#colorNav)" 
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ══ CONSOLIDATED REPORT TABLES ══ */}
      <div className="bg-[var(--background)] border border-[var(--border-color)] shadow-sm">
        
        {/* Table Tab Buttons */}
        <div className="flex border-b border-[var(--border-color)] bg-[var(--border-color)]/20 p-2 gap-2">
          <button
            onClick={() => setActiveTab("summary")}
            className={`px-4 py-2 text-xs font-semibold uppercase tracking-wider rounded transition-colors ${
              activeTab === "summary" 
                ? "bg-[var(--background)] text-brand-gold border border-[var(--border-color)] shadow-sm" 
                : "text-brand-slate hover:text-[var(--foreground)]"
            }`}
          >
            Summary
          </button>
          <button
            onClick={() => setActiveTab("detail")}
            className={`px-4 py-2 text-xs font-semibold uppercase tracking-wider rounded transition-colors ${
              activeTab === "detail" 
                ? "bg-[var(--background)] text-brand-gold border border-[var(--border-color)] shadow-sm" 
                : "text-brand-slate hover:text-[var(--foreground)]"
            }`}
          >
            Full Detail
          </button>
        </div>

        {/* SUMMARY TAB VIEW */}
        {activeTab === "summary" && (
          <div className="p-6 space-y-8 animate-in fade-in duration-300">
            {/* Value Section */}
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-widest text-brand-slate border-b border-[var(--border-color)] pb-2 mb-4">Value</h4>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <span className="block text-[11px] font-semibold text-brand-slate uppercase mb-1">Value at start</span>
                  <div className="text-xl font-medium">{currency_symbol}{value_start.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
                </div>
                <div>
                  <span className="block text-[11px] font-semibold text-brand-slate uppercase mb-1">Value at end</span>
                  <div className="text-xl font-medium">{currency_symbol}{value_end.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
                </div>
                <div>
                  <span className="block text-[11px] font-semibold text-brand-slate uppercase mb-1">Increase / (Decrease)</span>
                  <div className={`text-xl font-bold ${isIncreasePos ? "text-brand-green" : "text-brand-red"}`}>
                    {currency_symbol}{increase.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </div>
                </div>
              </div>
            </div>

            {/* Inflow / Outflow Summary */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8 pt-4 border-t border-[var(--border-color)]">
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-widest text-brand-slate border-b border-[var(--border-color)] pb-2 mb-4">Payments and transfers</h4>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-[var(--foreground)]">Payments and transfers (total)</span>
                  <span className="text-lg font-semibold font-mono">
                    {currency_symbol}{payments_transfers.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                </div>
              </div>
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-widest text-brand-slate border-b border-[var(--border-color)] pb-2 mb-4">Performance</h4>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-[var(--foreground)] flex items-center">
                    Performance <InfoTooltip text="Net change in asset values, dividends, and interest during the period." />
                  </span>
                  <span className={`text-lg font-bold font-mono ${performance.total >= 0 ? "text-brand-green" : "text-brand-red"}`}>
                    {currency_symbol}{performance.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* FULL DETAIL TAB VIEW */}
        {activeTab === "detail" && (
          <div className="overflow-x-auto p-4 animate-in fade-in duration-300">
            <table className="w-full text-left text-sm border-collapse">
              <thead>
                <tr className="border-b border-[var(--border-color)] bg-[var(--border-color)]/10 text-brand-slate text-[10px] uppercase tracking-wider font-semibold">
                  <th className="p-4 w-2/3">Category Description</th>
                  <th className="p-4 text-right">Amount ({base_currency})</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-color)] font-mono">
                
                {/* ══ Value Section ══ */}
                <tr className="bg-brand-navy-light/5">
                  <td className="p-4 font-serif font-bold text-brand-gold uppercase text-[11px] tracking-wide" colSpan={2}>Value</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Value at start</td>
                  <td className="p-4 text-right font-semibold">{currency_symbol}{value_start.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Value at end</td>
                  <td className="p-4 text-right font-semibold">{currency_symbol}{value_end.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr className="border-b-2 border-brand-slate/20 bg-brand-gold/5">
                  <td className="p-4 pl-8 font-semibold text-[var(--foreground)]">Increase / (Decrease)</td>
                  <td className={`p-4 text-right font-bold ${isIncreasePos ? "text-brand-green" : "text-brand-red"}`}>
                    {currency_symbol}{increase.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </td>
                </tr>

                {/* ══ Payments and Transfers Section ══ */}
                <tr className="bg-brand-navy-light/5">
                  <td className="p-4 font-serif font-bold text-brand-gold uppercase text-[11px] tracking-wide" colSpan={2}>Payments and Transfers</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Paid in</td>
                  <td className="p-4 text-right text-brand-green font-semibold">+{currency_symbol}{payments_transfers.paid_in.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Withdrawn</td>
                  <td className="p-4 text-right text-brand-red font-semibold">{payments_transfers.withdrawn.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Transferred</td>
                  <td className="p-4 text-right">{payments_transfers.transferred.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)] flex items-center">
                    Fees and charges <InfoTooltip text="Administrative and trading fees charged to the account." />
                  </td>
                  <td className="p-4 text-right text-brand-red font-semibold">{payments_transfers.fees_charges.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Tax</td>
                  <td className="p-4 text-right">{payments_transfers.tax.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Fund manager rebates</td>
                  <td className="p-4 text-right">+{currency_symbol}{payments_transfers.rebates.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr className="border-b-2 border-brand-slate/20 bg-brand-gold/5">
                  <td className="p-4 pl-8 font-semibold text-[var(--foreground)]">Payments and transfers (total)</td>
                  <td className="p-4 text-right font-bold">
                    {currency_symbol}{payments_transfers.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </td>
                </tr>

                {/* ══ Performance Section ══ */}
                <tr className="bg-brand-navy-light/5">
                  <td className="p-4 font-serif font-bold text-brand-gold uppercase text-[11px] tracking-wide" colSpan={2}>Performance</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)] flex items-center">
                    Investment value change <InfoTooltip text="Unrealised gain or loss from price changes of assets currently held." />
                  </td>
                  <td className={`p-4 text-right font-semibold ${performance.value_change >= 0 ? "text-brand-green" : "text-brand-red"}`}>
                    {currency_symbol}{performance.value_change.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)] flex items-center">
                    Investments sold <InfoTooltip text="Realised profit or loss from shares sold during the period." />
                  </td>
                  <td className={`p-4 text-right font-semibold ${performance.investments_sold >= 0 ? "text-brand-green" : "text-brand-red"}`}>
                    {currency_symbol}{performance.investments_sold.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Gross interest</td>
                  <td className="p-4 text-right text-brand-green font-semibold">+{currency_symbol}{performance.gross_interest.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Accrued interest</td>
                  <td className="p-4 text-right">{performance.accrued_interest.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr>
                  <td className="p-4 pl-8 text-[var(--foreground)]">Dividends</td>
                  <td className="p-4 text-right text-brand-green font-semibold">+{currency_symbol}{performance.dividends.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
                <tr className="border-b-2 border-brand-slate/20 bg-brand-gold/5">
                  <td className="p-4 pl-8 font-semibold text-[var(--foreground)] flex items-center">
                    Performance (total) <InfoTooltip text="Total return generated in the period (Value Change + Sells + Interest + Dividends)." />
                  </td>
                  <td className={`p-4 text-right font-bold ${performance.total >= 0 ? "text-brand-green" : "text-brand-red"}`}>
                    {currency_symbol}{performance.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </td>
                </tr>

              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
}
