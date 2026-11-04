import React, { useState, useEffect } from "react";
import { Search, Plus, X, BarChart2, Activity, ChevronsLeft } from "lucide-react";

interface TickerSidebarProps {
  selectedTicker: string;
  onSelectTicker: (ticker: string) => void;
  isOpen: boolean;
  onToggle: () => void;
  selectedAccount?: string;
  onSelectAccount?: (account: string) => void;
}

export function TickerSidebar({ selectedTicker, onSelectTicker, isOpen, onToggle, selectedAccount, onSelectAccount }: TickerSidebarProps) {
  const [currentTickers, setCurrentTickers] = useState<string[]>([]);
  const [recentExits, setRecentExits] = useState<string[]>([]);
  const [watchlistTickers, setWatchlistTickers] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  
  const [showAddModal, setShowAddModal] = useState(false);
  const [newTickerInput, setNewTickerInput] = useState("");
  const [availableAccounts, setAvailableAccounts] = useState<any[]>([]);

  useEffect(() => {
    if (onSelectAccount) {
      fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/ingestion/accounts`)
        .then(res => res.json())
        .then(d => {
          if (d.accounts) {
            const formatted = d.accounts.map((a: any) => 
              typeof a === "string" ? { name: a, classification: "Live" } : a
            );
            if (!formatted.some((a: any) => a.name === "Consolidated")) {
               formatted.unshift({ name: "Consolidated", classification: "Live" });
            }
            setAvailableAccounts(formatted);
          }
        })
        .catch(e => console.error("Failed to fetch accounts", e));
    }
  }, [onSelectAccount]);

  const loadTickers = () => {
    setLoading(true);
    const accountParam = selectedAccount ? `?account=${selectedAccount}` : "?account=Consolidated";
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/screener/tickers${accountParam}`)
      .then(res => res.json())
      .then(d => {
        if (d.current) setCurrentTickers(d.current);
        if (d.recent_exits) setRecentExits(d.recent_exits);
        if (d.watchlist) setWatchlistTickers(d.watchlist);
        
        // Auto-select first if none selected
        if (!selectedTicker && d.current && d.current.length > 0) {
          onSelectTicker(d.current[0]);
        }
        setLoading(false);
      })
      .catch(err => {
        console.error("Failed to fetch tickers", err);
        setLoading(false);
      });
  };

  useEffect(() => {
    loadTickers();
  }, [selectedAccount]);

  const handleAddNew = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTickerInput.trim()) return;
    const ticker = newTickerInput.trim().toUpperCase();
    
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/watchlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker })
      });
      if (!watchlistTickers.includes(ticker) && !currentTickers.includes(ticker) && !recentExits.includes(ticker)) {
        setWatchlistTickers(prev => [ticker, ...prev]);
      }
    } catch (err) {
      console.error("Failed to add to watchlist", err);
    }
    
    onSelectTicker(ticker);
    setNewTickerInput("");
    setShowAddModal(false);
  };

  const handleDeleteWatchlist = async (e: React.MouseEvent, ticker: string) => {
    e.stopPropagation();
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/watchlist/${ticker}`, {
        method: "DELETE"
      });
      setWatchlistTickers(prev => prev.filter(t => t !== ticker));
      if (selectedTicker === ticker) {
        if (currentTickers.length > 0) onSelectTicker(currentTickers[0]);
      }
    } catch (err) {
      console.error("Failed to delete from watchlist", err);
    }
  };

  const allTickers = [
    { label: "Current Holdings", items: currentTickers, isWatchlist: false },
    { label: "Recent Exits (Last 12M)", items: recentExits, isWatchlist: false },
    { label: "Watchlist Candidates", items: watchlistTickers, isWatchlist: true }
  ];

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div 
          className="md:hidden fixed inset-0 bg-black/50 backdrop-blur-sm z-40 transition-opacity"
          onClick={onToggle}
        />
      )}
      
      {/* Sidebar Panel */}
      <div className={`border-r border-[var(--border-color)] bg-[var(--background)] flex flex-col shrink-0 transition-all duration-300 h-full overflow-hidden
        fixed md:static inset-y-0 left-0 z-50 md:z-auto
        ${isOpen ? "w-72 md:w-72 translate-x-0" : "w-0 -translate-x-full border-transparent"}
      `}>
      <div className="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
        <h2 className="font-semibold text-[var(--foreground)]">Asset Selection</h2>
        <button onClick={onToggle} className="p-1.5 rounded hover:bg-[var(--foreground)]/5 text-[var(--foreground)]/70">
          <ChevronsLeft className="w-4 h-4" />
        </button>
      </div>

      {onSelectAccount && availableAccounts.length > 0 && (
        <div className="p-4 border-b border-[var(--border-color)] bg-[var(--foreground)]/5">
          <label className="block text-xs font-semibold tracking-wider text-[var(--foreground)]/50 uppercase mb-2">
            Account Context
          </label>
          <select 
            value={selectedAccount || "Consolidated"}
            onChange={(e) => onSelectAccount(e.target.value)}
            className="w-full px-3 py-2 text-sm bg-[var(--background)] border border-[var(--border-color)] rounded-md focus:outline-none focus:border-brand-gold text-[var(--foreground)] font-medium"
          >
            {availableAccounts.map((acc, idx) => (
              <option key={idx} value={acc.name}>
                {acc.classification === "Third Party EUR" ? "🇪🇺 " : (acc.classification === "Sandbox" ? "🧪 " : "✅ ")}
                {acc.classification} - {acc.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="p-4">
        <button 
          onClick={() => setShowAddModal(true)}
          className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-brand-gold/10 hover:bg-brand-gold/20 text-brand-gold border border-brand-gold/20 rounded-md transition-colors text-sm font-medium"
        >
          <Plus className="w-4 h-4" />
          Add to Watchlist
        </button>

        {showAddModal && (
          <form onSubmit={handleAddNew} className="mt-3 p-3 bg-[var(--foreground)]/5 border border-[var(--border-color)] rounded-md">
            <label className="block text-xs font-medium text-[var(--foreground)]/70 mb-1">Add Ticker to Watchlist</label>
            <div className="flex gap-2">
              <input 
                type="text"
                value={newTickerInput}
                onChange={e => setNewTickerInput(e.target.value)}
                placeholder="e.g. AAPL, VUSA.L"
                className="flex-1 px-2 py-1.5 text-sm bg-[var(--background)] border border-[var(--border-color)] rounded-md focus:outline-none focus:border-brand-gold uppercase"
                autoFocus
              />
              <button type="submit" className="px-3 py-1.5 bg-brand-gold text-[var(--background)] text-sm font-medium rounded-md">
                Add
              </button>
            </div>
          </form>
        )}
        
        <div className="mt-4 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--foreground)]/40" />
          <input 
            type="text" 
            placeholder="Search tickers..." 
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-[var(--foreground)]/5 border border-[var(--border-color)] rounded-md text-sm text-[var(--foreground)] focus:outline-none focus:border-brand-gold/50"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {loading ? (
          <div className="p-4 text-center text-sm text-[var(--foreground)]/50">Loading tickers...</div>
        ) : (
          <div className="space-y-6 px-2">
            {allTickers.map(group => {
              const filtered = group.items.filter(t => t.toLowerCase().includes(searchQuery.toLowerCase()));
              if (filtered.length === 0) return null;
              
              return (
                <div key={group.label}>
                  <div className="text-xs font-semibold tracking-wider text-[var(--foreground)]/40 uppercase mb-2 ml-2 flex items-center justify-between">
                    <span>{group.label}</span>
                    <span className="text-[10px] bg-[var(--foreground)]/10 px-1.5 py-0.5 rounded-full">{filtered.length}</span>
                  </div>
                  <div className="space-y-1">
                    {filtered.map(ticker => (
                      <div
                        key={ticker}
                        onClick={() => onSelectTicker(ticker)}
                        className={`group flex items-center justify-between w-full px-3 py-2 rounded-md text-sm transition-colors cursor-pointer ${
                          selectedTicker === ticker 
                            ? "bg-brand-gold/10 text-brand-gold font-medium border border-brand-gold/20" 
                            : "text-[var(--foreground)]/80 hover:bg-[var(--foreground)]/5 border border-transparent"
                        }`}
                      >
                        <span className="truncate">{ticker}</span>
                        {group.isWatchlist && (
                          <button
                            onClick={(e) => handleDeleteWatchlist(e, ticker)}
                            className="opacity-0 group-hover:opacity-100 hover:text-red-400 p-0.5 rounded transition-opacity"
                            title="Remove from watchlist"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        </div>
      </div>
    </>
  );
}
