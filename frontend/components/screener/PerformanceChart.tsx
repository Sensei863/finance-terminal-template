"use client";

import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
} from "recharts";

interface ChartDataPoint {
  date: string;
  asset_pct: number | null;
  bench_pct?: number | null;
  port_pct?: number | null;
}

interface MarkerPoint {
  date: string;
  action?: string;
  amount?: number;
  qty?: number;
  price?: number;
}

interface PerformanceChartProps {
  data: ChartDataPoint[];
  trades: MarkerPoint[];
  dividends: MarkerPoint[];
  ticker: string;
  benchmark: string;
}

export function PerformanceChart({ data, trades, dividends, ticker, benchmark }: PerformanceChartProps) {
  if (!data || data.length === 0) {
    return <div className="h-[450px] flex items-center justify-center text-gray-500">No chart data available</div>;
  }

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white dark:bg-brand-navy p-3 border border-brand-gold/30 shadow-lg rounded-md text-sm">
          <p className="font-semibold text-gray-800 dark:text-gray-200 mb-2">{label}</p>
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center gap-2 mb-1">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
              <span className="text-gray-600 dark:text-gray-400">{entry.name}:</span>
              <span className="font-medium text-gray-900 dark:text-white">
                {entry.value !== null ? `${entry.value.toFixed(2)}%` : "N/A"}
              </span>
            </div>
          ))}
          
          {/* Custom logic to show trades/divs on this date could be added here */}
          {trades.filter(t => t.date === label).map((t, i) => (
            <div key={`t-${i}`} className={`mt-2 text-xs font-bold ${t.action === 'Buy' ? 'text-emerald-500' : 'text-red-500'}`}>
              {t.action} {t.qty} @ {t.price?.toFixed(2)}
            </div>
          ))}
          {dividends.filter(d => d.date === label).map((d, i) => (
            <div key={`d-${i}`} className="mt-2 text-xs font-bold text-amber-500">
              Dividend: {d.amount?.toFixed(4)}
            </div>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="h-[450px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(156, 163, 175, 0.2)" />
          <XAxis 
            dataKey="date" 
            tick={{ fontSize: 12, fill: "rgba(156, 163, 175, 0.8)" }}
            tickMargin={10}
            minTickGap={30}
          />
          <YAxis 
            tickFormatter={(val) => `${val}%`}
            tick={{ fontSize: 12, fill: "rgba(156, 163, 175, 0.8)" }}
            width={50}
            domain={['auto', 'auto']}
          />
          <Tooltip content={<CustomTooltip />} />
          
          {/* Custom Legend */}
          <div className="flex flex-wrap items-center justify-center gap-6 mt-4 text-xs font-medium text-brand-slate">
            <div className="flex items-center gap-2"><div className="w-3 h-0.5 bg-[#0284c7]"></div> {ticker}</div>
            <div className="flex items-center gap-2"><div className="w-3 h-0.5 border-t border-dashed border-[#64748b]"></div> {benchmark}</div>
            <div className="flex items-center gap-2"><div className="w-3 h-0.5 bg-[#10b981]"></div> Portfolio</div>
            <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-full bg-[#10b981] border border-white"></div> Buy</div>
            <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-full bg-[#ef4444] border border-white"></div> Sell</div>
            <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-[#f59e0b] border border-white"></div> Dividend</div>
          </div>
          
          <Line 
            type="monotone" 
            dataKey="asset_pct" 
            name={`${ticker} (Selected)`}
            stroke="#0284c7" 
            strokeWidth={3}
            dot={false}
            activeDot={{ r: 6 }}
            isAnimationActive={false}
          />
          
          <Line 
            type="monotone" 
            dataKey="bench_pct" 
            name={`Index: ${benchmark}`}
            stroke="#64748b" 
            strokeWidth={1.5}
            strokeDasharray="5 5"
            dot={false}
            isAnimationActive={false}
          />
          
          <Line 
            type="monotone" 
            dataKey="port_pct" 
            name="Portfolio (Consolidated)"
            stroke="#10b981" 
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />

          {trades.map((t, i) => {
            const pt = data.find(d => d.date === t.date);
            if (pt && pt.asset_pct !== undefined && pt.asset_pct !== null) {
              return (
                <ReferenceDot 
                  key={`trade-${i}`}
                  x={t.date} 
                  y={pt.asset_pct} 
                  r={5} 
                  fill={t.action === 'Buy' ? '#10b981' : '#ef4444'} 
                  stroke="white"
                  strokeWidth={2}
                />
              );
            }
            return null;
          })}
          
          {dividends.map((d, i) => {
            const pt = data.find(pt => pt.date === d.date);
            if (pt && pt.asset_pct !== undefined && pt.asset_pct !== null) {
              return (
                <ReferenceDot 
                  key={`div-${i}`}
                  x={d.date} 
                  y={pt.asset_pct} 
                  r={4} 
                  fill="#f59e0b" 
                  stroke="white"
                  strokeWidth={1}
                />
              );
            }
            return null;
          })}

        </LineChart>
      </ResponsiveContainer>

      {/* Custom Legend */}
      <div className="flex flex-wrap items-center justify-center gap-6 mt-6 text-xs font-medium text-brand-slate">
        <div className="flex items-center gap-2"><div className="w-3 h-0.5 bg-[#0284c7]"></div> {ticker}</div>
        <div className="flex items-center gap-2"><div className="w-3 h-0.5 border-t border-dashed border-[#64748b]"></div> {benchmark}</div>
        <div className="flex items-center gap-2"><div className="w-3 h-0.5 bg-[#10b981]"></div> Portfolio</div>
        <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-full bg-[#10b981] border border-[var(--background)]"></div> Buy</div>
        <div className="flex items-center gap-1.5"><div className="w-2.5 h-2.5 rounded-full bg-[#ef4444] border border-[var(--background)]"></div> Sell</div>
        <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-[#f59e0b] border border-[var(--background)]"></div> Dividend</div>
      </div>
    </div>
  );
}
