import React from "react";

interface TrendScannerProps {
  trend: string; // UPTREND, DOWNTREND, NEUTRAL
  sma50: number | null;
  sma200: number | null;
  distSma50: number | null;
  distSma200: number | null;
  
  rsi: number | null;
  
  bbPos: number | null;
  bbUpper: number | null;
  bbLower: number | null;
  
  macd: number | null;
  macdSignal: number | null;
  macdHist: number | null;
}

export function TrendScanner({
  trend, sma50, sma200, distSma50, distSma200,
  rsi,
  bbPos, bbUpper, bbLower,
  macd, macdSignal, macdHist
}: TrendScannerProps) {
  
  const formatPct = (val: number | null) => {
    if (val === null) return "N/A";
    return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(2)}%`;
  };

  const formatNum = (val: number | null) => {
    if (val === null) return "N/A";
    return val.toFixed(2);
  };

  const formatMacd = (val: number | null) => {
    if (val === null) return "N/A";
    return val.toFixed(3);
  };

  // Trend Badge
  const getTrendStyle = (t: string) => {
    if (t === "UPTREND") return "text-emerald-600 dark:text-emerald-400";
    if (t === "DOWNTREND") return "text-red-600 dark:text-red-400";
    return "text-brand-navy dark:text-gray-300";
  };

  // RSI Badge
  let rsiLabel = "Neutral";
  let rsiStyle = "text-brand-navy dark:text-gray-300";
  if (rsi !== null) {
    if (rsi >= 70) { rsiLabel = "Overbought"; rsiStyle = "text-red-600 dark:text-red-400"; }
    else if (rsi <= 30) { rsiLabel = "Oversold"; rsiStyle = "text-emerald-600 dark:text-emerald-400"; }
  }

  // MACD Badge
  const macdBullish = macd !== null && macdSignal !== null && macd > macdSignal;
  const macdLabel = macdBullish ? "Bullish" : "Bearish";
  const macdStyle = macdBullish ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400";

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-6 p-6 bg-white dark:bg-brand-navy/30 rounded-xl border border-brand-gold/20 shadow-sm">
      
      {/* 1. Trend Regime */}
      <div>
        <h5 className="text-sm text-brand-navy/60 dark:text-gray-400 font-medium mb-2">Trend Regime</h5>
        <div className={`text-2xl font-bold ${getTrendStyle(trend)} uppercase`}>
          {trend}
        </div>
        <div className="mt-2 text-xs text-brand-navy/70 dark:text-gray-400 space-y-1">
          <div><span className="font-semibold">SMA 50:</span> {formatNum(sma50)} ({formatPct(distSma50)})</div>
          <div><span className="font-semibold">SMA 200:</span> {formatNum(sma200)} ({formatPct(distSma200)})</div>
        </div>
      </div>

      {/* 2. Momentum (RSI) */}
      <div>
        <h5 className="text-sm text-brand-navy/60 dark:text-gray-400 font-medium mb-2">Momentum (RSI)</h5>
        <div className="text-2xl font-bold text-brand-navy dark:text-white flex items-center gap-2">
          {rsi !== null ? rsi.toFixed(1) : "N/A"}
          <span className={`text-[10px] px-2 py-0.5 rounded-full bg-black/5 dark:bg-white/10 ${rsiStyle} uppercase tracking-wider`}>
            {rsiLabel}
          </span>
        </div>
        <div className="mt-2 text-xs text-brand-navy/70 dark:text-gray-400 leading-relaxed">
          14-Day Relative Strength Index.<br/>
          Status indicates overbought/oversold levels.
        </div>
      </div>

      {/* 3. Volatility (BB) */}
      <div>
        <h5 className="text-sm text-brand-navy/60 dark:text-gray-400 font-medium mb-2">Volatility & Bands</h5>
        <div className="text-2xl font-bold text-brand-navy dark:text-white flex items-baseline gap-1">
          {bbPos !== null ? `${(bbPos * 100).toFixed(1)}%` : "N/A"}
          <span className="text-xs font-normal text-brand-navy/60 dark:text-gray-400">%B</span>
        </div>
        <div className="mt-2 text-xs text-brand-navy/70 dark:text-gray-400 space-y-1">
          <div><span className="font-semibold">BB Upper:</span> {formatNum(bbUpper)}</div>
          <div><span className="font-semibold">BB Lower:</span> {formatNum(bbLower)}</div>
        </div>
      </div>

      {/* 4. MACD */}
      <div>
        <h5 className="text-sm text-brand-navy/60 dark:text-gray-400 font-medium mb-2">MACD Indicator</h5>
        <div className="text-2xl font-bold text-brand-navy dark:text-white flex items-center gap-2">
          {formatMacd(macd)}
          {macd !== null && (
            <span className={`text-[10px] px-2 py-0.5 rounded-full bg-black/5 dark:bg-white/10 ${macdStyle} uppercase tracking-wider`}>
              {macdLabel}
            </span>
          )}
        </div>
        <div className="mt-2 text-xs text-brand-navy/70 dark:text-gray-400 space-y-1">
          <div><span className="font-semibold">Signal Line:</span> {formatMacd(macdSignal)}</div>
          <div><span className="font-semibold">Histogram:</span> {formatMacd(macdHist)}</div>
        </div>
      </div>

    </div>
  );
}
