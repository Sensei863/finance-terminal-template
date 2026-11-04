import React, { useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

interface Trade {
  date: string;
  action: string;
  qty: number | null;
  price: number | null;
  amount: number | null;
  account?: string;
}

interface Dividend {
  date: string;
  amount: number | null;
  shares?: number | null;
}

interface ActivityTableProps {
  trades: Trade[];
  dividends: Dividend[];
  currency: string;
  currentPrice: number | null;
}

export function ActivityTable({ trades, dividends, currency, currentPrice }: ActivityTableProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const allActivity = useMemo(() => {
    const combined = [];
    
    if (trades && trades.length > 0) {
      for (const t of trades) {
        combined.push({
          date: t.date,
          type: t.action === "Dividend" ? "Dividend" : "Trade",
          action: t.action === "Dividend" ? "-" : t.action,
          shares: t.qty,
          price: t.price,
          amount: t.amount,
          account: t.account,
        });
      }
    }
    const ledgerHasDividends = trades && trades.some(t => t.action === 'Dividend');
    
    if (dividends && dividends.length > 0 && !ledgerHasDividends) {
      for (const d of dividends) {
        combined.push({
          date: d.date,
          type: "Dividend",
          action: "-",
          shares: d.shares || null,
          price: null,
          amount: d.amount,
          account: "-",
        });
      }
    }
    
    // Sort descending by date
    return combined.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
  }, [trades, dividends]);

  if (allActivity.length === 0) return null;

  return (
    <div className="bg-[var(--background)] rounded-xl border border-[var(--border-color)] shadow-sm overflow-hidden mt-8">
      <button 
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 bg-blue-50/50 dark:bg-blue-900/10 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors border-b border-[var(--border-color)]"
      >
        <div className="flex items-center gap-2">
          <span className="text-xl">📜</span>
          <h3 className="font-semibold text-[var(--foreground)] tracking-wide">Activity History (Trades & Dividends)</h3>
        </div>
        {isExpanded ? <ChevronUp className="w-5 h-5 text-brand-slate" /> : <ChevronDown className="w-5 h-5 text-brand-slate" />}
      </button>

      {isExpanded && (
        <div className="overflow-x-auto p-4">
          <table className="w-full text-sm text-left">
            <thead className="text-[11px] uppercase tracking-widest text-brand-slate border-b border-[var(--border-color)] bg-[var(--background)]">
              <tr>
                <th className="px-4 py-3 font-semibold">Date</th>
                <th className="px-4 py-3 font-semibold">Type</th>
                <th className="px-4 py-3 font-semibold">Action</th>
                <th className="px-4 py-3 font-semibold">Account</th>
                <th className="px-4 py-3 font-semibold text-right">Shares</th>
                <th className="px-4 py-3 font-semibold text-right">Price</th>
                <th className="px-4 py-3 font-semibold text-right">Δ vs Current</th>
                <th className="px-4 py-3 font-semibold text-right">Value/Amount</th>
              </tr>
            </thead>
            <tbody>
              {allActivity.map((item, idx) => {
                let deltaPct = null;
                if (item.type === 'Trade' && item.price && currentPrice) {
                  deltaPct = ((currentPrice / item.price) - 1) * 100;
                }

                return (
                  <tr 
                    key={idx} 
                    className={`border-b border-[var(--border-color)]/50 last:border-0 hover:bg-black/5 dark:hover:bg-white/5 transition-colors ${item.type === 'Dividend' ? 'bg-green-50/30 dark:bg-green-900/10' : ''}`}
                  >
                    <td className="px-4 py-3 text-[var(--foreground)] whitespace-nowrap">{item.date}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded-full text-[10px] font-bold tracking-wider ${
                        item.type === 'Trade' 
                          ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-300' 
                          : 'bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-300'
                      }`}>
                        {item.type}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`font-medium ${
                        item.action === 'Buy' ? 'text-brand-green' : 
                        item.action === 'Sell' ? 'text-brand-red' : 
                        'text-brand-slate'
                      }`}>
                        {item.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[var(--foreground)]">{item.account || "-"}</td>
                    <td className="px-4 py-3 text-right font-mono text-[var(--foreground)]">
                      {item.shares !== null && item.shares !== undefined ? item.shares.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '-'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[var(--foreground)]">
                      {item.price !== null && item.price !== undefined ? `${currency} ${item.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '-'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono font-bold">
                      {deltaPct !== null ? (
                        <span className={deltaPct > 0 ? "text-brand-green" : deltaPct < 0 ? "text-brand-red" : "text-[var(--foreground)]"}>
                          {deltaPct > 0 ? "+" : ""}{deltaPct.toFixed(2)}%
                        </span>
                      ) : '-'}
                    </td>
                    <td className="px-4 py-3 text-right font-mono font-bold text-[var(--foreground)]">
                      {item.amount !== null && item.amount !== undefined ? `${currency} ${Math.abs(item.amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '-'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
