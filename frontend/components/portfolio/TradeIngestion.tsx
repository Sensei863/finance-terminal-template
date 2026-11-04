import React, { useState, useEffect } from "react";
import { UploadCloud, CheckCircle2, AlertCircle, Trash2, Search } from "lucide-react";

interface IngestionProps {
  account: string;
}

function formatAmount(numVal: number): string {
  if (isNaN(numVal) || numVal === 0) return "0.00";
  const absVal = Math.abs(numVal);
  const formatted = absVal.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
  return numVal < 0 ? `(${formatted})` : formatted;
}

export function TradeIngestion({ account }: IngestionProps) {
  const [mode, setMode] = useState<"manual" | "pdf" | "bulk">("manual");
  
  // Staging for manual entry
  const [stagedTrades, setStagedTrades] = useState<any[]>([]);
  
  // Form state
  const [action, setAction] = useState("Buy");
  const [date, setDate] = useState(new Date().toISOString().split("T")[0]);
  const [assetName, setAssetName] = useState("");
  const [qty, setQty] = useState<number | "">("");
  const [price, setPrice] = useState<number | "">("");
  const [ticker, setTicker] = useState("");
  const [netAmount, setNetAmount] = useState<number | "">("");
  
  const [isCommitting, setIsCommitting] = useState(false);
  const [message, setMessage] = useState({ text: "", type: "" });
  const [isResolving, setIsResolving] = useState(false);
  
  // Ledger state
  const [ledger, setLedger] = useState<any[]>([]);
  const [isLoadingLedger, setIsLoadingLedger] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<number | null>(null);

  const fetchLedger = async () => {
    if (!account || account === "Consolidated") return;
    setIsLoadingLedger(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/ingestion/ledger/${encodeURIComponent(account)}`);
      const data = await res.json();
      if (res.ok) {
        setLedger(data.ledger || []);
      } else {
        setLedger([]);
      }
    } catch (e) {
      console.error(e);
      setLedger([]);
    } finally {
      setIsLoadingLedger(false);
    }
  };

  useEffect(() => {
    fetchLedger();
  }, [account]);

  const handleDeleteRow = async (idx: number) => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/ingestion/ledger/${encodeURIComponent(account)}/${idx}`, {
        method: "DELETE"
      });
      if (res.ok) {
        setMessage({ text: "Row deleted successfully.", type: "success" });
        setPendingDelete(null);
        fetchLedger();
      } else {
        const d = await res.json();
        setMessage({ text: d.detail || "Failed to delete row.", type: "error" });
      }
    } catch (e: any) {
      setMessage({ text: e.message, type: "error" });
    }
  };

  const handleResolveTicker = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (!assetName) {
      setMessage({ text: "Asset Name required for resolution", type: "error" });
      return;
    }
    setIsResolving(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/ingestion/resolve-tickers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account: account,
          asset_names: [assetName]
        })
      });
      const data = await res.json();
      if (res.ok && data.resolved && data.resolved[assetName]) {
        setTicker(data.resolved[assetName]);
        setMessage({ text: "Ticker resolved successfully", type: "success" });
      } else {
        setMessage({ text: "Could not resolve ticker automatically.", type: "error" });
      }
    } catch (e: any) {
      setMessage({ text: e.message, type: "error" });
    } finally {
      setIsResolving(false);
    }
  };

  const handleStageTrade = (e: React.FormEvent) => {
    e.preventDefault();
    let computedNet = Number(netAmount) || 0.0;
    const isTrade = action === "Buy" || action === "Sell";
    
    if (isTrade && computedNet === 0.0) {
      const q = Number(qty) || 0.0;
      const p = Number(price) || 0.0;
      computedNet = action === "Buy" ? -(q * p) : (q * p);
    }
    
    const newTrade = {
      Date: date,
      Action: action,
      "Asset Name": assetName,
      Qty: Number(qty) || 0,
      Price: Number(price) || 0,
      "Net Amount": computedNet,
      "Auto Ticker": ticker
    };
    
    setStagedTrades([...stagedTrades, newTrade]);
    
    // reset form
    setAssetName("");
    setQty("");
    setPrice("");
    setTicker("");
    setNetAmount("");
    setMessage({ text: "Trade staged for review", type: "success" });
  };

  const removeStagedTrade = (index: number) => {
    const newTrades = [...stagedTrades];
    newTrades.splice(index, 1);
    setStagedTrades(newTrades);
  };

  const updateStagedTrade = (index: number, field: string, value: any) => {
    const newTrades = [...stagedTrades];
    newTrades[index] = { ...newTrades[index], [field]: value };
    setStagedTrades(newTrades);
  };

  const handleCommit = async () => {
    if (stagedTrades.length === 0) return;
    setIsCommitting(true);
    setMessage({ text: "", type: "" });
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/ingestion/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account, trades: stagedTrades })
      });
      const data = await res.json();
      if (res.ok) {
        setStagedTrades([]);
        setMessage({ text: `Successfully committed ${data.count} trades to ${account}.`, type: "success" });
      } else {
        throw new Error(data.detail || "Commit failed");
      }
    } catch (e: any) {
      setMessage({ text: e.message, type: "error" });
    } finally {
      setIsCommitting(false);
    }
  };

  const [isUploading, setIsUploading] = useState(false);

  const handleSpreadsheetUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setIsUploading(true);
    setMessage({ text: "", type: "" });
    
    const formData = new FormData();
    formData.append("account", account);
    formData.append("file", file);
    
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/ingestion/parse-spreadsheet`, {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (res.ok && data.parsed_trades) {
        const newStaged = data.parsed_trades.map((t: any) => ({
          Date: t.Date || new Date().toISOString().split("T")[0],
          Action: t.Action || "Buy",
          "Asset Name": t["Asset Name"] || "",
          Qty: Number(t.Qty) || 0,
          Price: Number(t.Price) || 0,
          "Net Amount": Number(t["Net Amount"]) || 0,
          "Auto Ticker": t["Auto Ticker"] || ""
        }));
        
        setStagedTrades([...stagedTrades, ...newStaged]);
        setMode("manual");
        setMessage({ text: `Parsed spreadsheet! Staged ${newStaged.length} entries for review.`, type: "success" });
      } else {
        setMessage({ text: data.detail || "Failed to parse spreadsheet.", type: "error" });
      }
    } catch (err: any) {
      setMessage({ text: err.message || "Upload failed", type: "error" });
    } finally {
      setIsUploading(false);
      e.target.value = "";
    }
  };

  const handlePdfUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setIsUploading(true);
    setMessage({ text: "", type: "" });
    
    const formData = new FormData();
    formData.append("account", account);
    formData.append("file", file);
    
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/ingestion/parse-pdf`, {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (res.ok && data.parsed_trades) {
        const newStaged = data.parsed_trades.map((t: any) => ({
          Date: t.Date || new Date().toISOString().split("T")[0],
          Action: t.Action || "Buy",
          "Asset Name": t["Asset Name"] || "",
          Qty: Number(t.Qty) || 0,
          Price: Number(t.Price) || 0,
          "Net Amount": Number(t["Net Amount"]) || 0,
          "Auto Ticker": t["Auto Ticker"] || ""
        }));
        
        setStagedTrades([...stagedTrades, ...newStaged]);
        setMode("manual"); // switch back to review staged trades
        setMessage({ text: `Parsed contract note! Staged ${newStaged.length} entries for review.`, type: "success" });
      } else {
        setMessage({ text: data.detail || "Failed to parse contract note.", type: "error" });
      }
    } catch (err: any) {
      setMessage({ text: err.message || "Upload failed", type: "error" });
    } finally {
      setIsUploading(false);
      e.target.value = "";
    }
  };

  if (account === "Consolidated") {
    return (
      <div className="max-w-xl mx-auto text-center py-12 px-6 border border-brand-red/30 bg-brand-red/5 mt-8 animate-in fade-in duration-500">
        <AlertCircle className="w-12 h-12 text-brand-red mx-auto mb-4" />
        <h3 className="text-xl font-serif text-brand-gold mb-2">Consolidated Ledger Cannot Be Edited</h3>
        <p className="text-sm text-brand-slate mb-6">
          The "Consolidated" view is a read-only combination of all live portfolios. 
          To record transactions, please select an active account ledger (e.g., ISA, SIPP, or Papa) from the sidebar.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto animate-in fade-in duration-500">
      
      {/* Settings Row */}
      <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm mb-8 flex items-center justify-between">
        <div className="flex gap-4">
          {["manual", "pdf", "bulk"].map(m => (
            <button
              key={m}
              onClick={() => setMode(m as any)}
              className={`px-4 py-2 text-sm uppercase tracking-wider font-semibold transition-colors border ${
                mode === m 
                  ? "border-brand-gold bg-[var(--hover-bg)] text-brand-gold" 
                  : "border-transparent text-brand-slate hover:bg-[var(--border-color)]"
              }`}
            >
              {m === "pdf" ? "Single PDF" : m === "bulk" ? "Bulk CSV" : "Manual Entry"}
            </button>
          ))}
        </div>
      </div>

      {message.text && (
        <div className={`p-4 mb-8 text-sm flex items-center gap-2 border ${
          message.type === "success" 
            ? "border-brand-green/50 bg-brand-green/10 text-brand-green" 
            : "border-brand-red/50 bg-brand-red/10 text-brand-red"
        }`}>
          {message.type === "success" ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
          {message.text}
        </div>
      )}

      {/* Mode Render */}
      {mode === "manual" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          
          {/* Form */}
          <div className="lg:col-span-1 bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm h-fit">
            <h3 className="text-lg font-serif text-brand-gold mb-6 border-b border-[var(--border-color)] pb-2">Record Transaction</h3>
            <form onSubmit={handleStageTrade} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-brand-slate uppercase tracking-wider mb-1">Action</label>
                <select 
                  value={action} 
                  onChange={(e) => {
                    const newAction = e.target.value;
                    setAction(newAction);
                    if (newAction === "Transfer") {
                      setAssetName("Cash Transfer");
                    } else if (newAction === "Fee") {
                      setAssetName("Account Fee");
                    } else if (newAction === "Interest") {
                      setAssetName("Cash Interest");
                    } else if (["Cash Transfer", "Account Fee", "Cash Interest"].includes(assetName)) {
                      setAssetName("");
                    }
                  }}
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-sm text-[var(--foreground)] outline-none focus:border-brand-gold"
                >
                  {["Buy", "Sell", "Transfer", "Fee", "Dividend", "Interest"].map(a => <option key={a}>{a}</option>)}
                </select>
              </div>
              
              <div>
                <label className="block text-xs font-semibold text-brand-slate uppercase tracking-wider mb-1">Date</label>
                <input 
                  type="date" 
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                  required
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-sm text-[var(--foreground)] outline-none focus:border-brand-gold [color-scheme:dark]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-brand-slate uppercase tracking-wider mb-1">
                  Asset Name {!(action === "Buy" || action === "Sell" || action === "Dividend") && <span className="text-brand-slate/60 normal-case font-normal">(Optional)</span>}
                </label>
                <input 
                  type="text" 
                  value={assetName}
                  onChange={(e) => setAssetName(e.target.value)}
                  required={action === "Buy" || action === "Sell" || action === "Dividend"}
                  placeholder={
                    action === "Interest" ? "e.g. Cash Interest" :
                    action === "Fee" ? "e.g. Account Fee" :
                    action === "Transfer" ? "e.g. Cash Transfer" :
                    "e.g. Apple Inc."
                  }
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-sm text-[var(--foreground)] outline-none focus:border-brand-gold"
                />
              </div>

              {(action === "Buy" || action === "Sell") && (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-brand-slate uppercase tracking-wider mb-1">Quantity</label>
                    <input 
                      type="number" step="any"
                      value={qty}
                      onChange={(e) => setQty(e.target.value as any)}
                      required
                      className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-sm text-[var(--foreground)] outline-none focus:border-brand-gold"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-brand-slate uppercase tracking-wider mb-1">Price</label>
                    <input 
                      type="number" step="any"
                      value={price}
                      onChange={(e) => setPrice(e.target.value as any)}
                      required
                      className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-sm text-[var(--foreground)] outline-none focus:border-brand-gold"
                    />
                  </div>
                </div>
              )}

              {(action === "Buy" || action === "Sell" || action === "Dividend") && (
                <div>
                  <label className="block text-xs font-semibold text-brand-slate uppercase tracking-wider mb-1">Auto Ticker</label>
                  <div className="flex gap-2">
                    <input 
                      type="text" 
                      value={ticker}
                      onChange={(e) => setTicker(e.target.value)}
                      placeholder="e.g. VUSA.L"
                      className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-sm text-[var(--foreground)] outline-none focus:border-brand-gold uppercase"
                    />
                    <button 
                      onClick={handleResolveTicker}
                      disabled={isResolving}
                      className="p-2 border border-[var(--border-color)] hover:border-brand-gold text-brand-slate hover:text-brand-gold transition-colors disabled:opacity-50"
                      title="AI Resolve Ticker"
                    >
                      <Search className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-brand-slate uppercase tracking-wider mb-1">Net Amount</label>
                <input 
                  type="number" step="any"
                  value={netAmount}
                  onChange={(e) => setNetAmount(e.target.value as any)}
                  placeholder="Auto-calculates if 0"
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-sm text-[var(--foreground)] outline-none focus:border-brand-gold"
                />
              </div>

              <button 
                type="submit"
                className="w-full mt-4 bg-transparent border border-brand-gold text-brand-gold hover:bg-brand-gold hover:text-[var(--background)] p-3 text-sm font-semibold tracking-wider uppercase transition-colors"
              >
                Stage Entry
              </button>
            </form>
          </div>

          {/* Staging Area */}
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm">
              <div className="flex items-center justify-between mb-6 border-b border-[var(--border-color)] pb-2">
                <h3 className="text-lg font-serif text-brand-gold">Review & Commit</h3>
                <span className="text-sm font-mono text-brand-slate">{stagedTrades.length} rows staged</span>
              </div>
              
              <div className="overflow-x-auto mb-6">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--border-color)] bg-[var(--hover-bg)]">
                      <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold">Date</th>
                      <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold">Action</th>
                      <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold">Asset</th>
                      <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold text-right">Net</th>
                      <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold text-center">Ticker</th>
                      <th className="p-3"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {stagedTrades.map((t, idx) => (
                      <tr key={idx} className="border-b border-[var(--border-color)] hover:bg-[var(--hover-bg)] transition-colors text-sm">
                        <td className="p-3">
                          <input type="date" value={t.Date || ""} onChange={(e) => updateStagedTrade(idx, "Date", e.target.value)} className="w-full bg-transparent border-b border-transparent hover:border-[var(--border-color)] focus:border-brand-gold outline-none text-[var(--foreground)] [color-scheme:dark]" />
                        </td>
                        <td className="p-3">
                          <select value={t.Action || ""} onChange={(e) => updateStagedTrade(idx, "Action", e.target.value)} className="w-full bg-transparent outline-none text-[var(--foreground)]">
                            {["Buy", "Sell", "Transfer", "Fee", "Dividend", "Interest"].map(a => <option key={a} value={a} className="bg-[var(--background)]">{a}</option>)}
                          </select>
                        </td>
                        <td className="p-3 max-w-[200px]">
                          <input type="text" value={t["Asset Name"] || ""} onChange={(e) => updateStagedTrade(idx, "Asset Name", e.target.value)} className="w-full bg-transparent border-b border-transparent hover:border-[var(--border-color)] focus:border-brand-gold outline-none text-[var(--foreground)] truncate" />
                        </td>
                        <td className="p-3 font-mono text-right">
                          <input type="number" step="any" value={t["Net Amount"] !== undefined ? t["Net Amount"] : ""} onChange={(e) => updateStagedTrade(idx, "Net Amount", parseFloat(e.target.value) || 0)} className="w-24 bg-transparent border-b border-transparent hover:border-[var(--border-color)] focus:border-brand-gold outline-none text-right text-[var(--foreground)]" />
                        </td>
                        <td className="p-3 text-center">
                          <input type="text" value={t["Auto Ticker"] || ""} onChange={(e) => updateStagedTrade(idx, "Auto Ticker", e.target.value)} className="w-20 bg-transparent border-b border-transparent hover:border-[var(--border-color)] focus:border-brand-gold outline-none text-center text-[var(--foreground)] uppercase" />
                        </td>
                        <td className="p-3 text-right">
                          <button onClick={() => removeStagedTrade(idx)} className="text-brand-red hover:text-brand-red/80 transition-colors">
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {stagedTrades.length === 0 && (
                      <tr><td colSpan={6} className="p-8 text-center text-brand-slate text-sm">No trades staged.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              <button 
                onClick={handleCommit}
                disabled={stagedTrades.length === 0 || isCommitting}
                className="w-full bg-brand-gold text-[var(--background)] hover:bg-[#b58b38] p-3 text-sm font-semibold tracking-wider uppercase transition-colors disabled:opacity-50"
              >
                {isCommitting ? "Committing to Ledger..." : `Commit to ${account}`}
              </button>
            </div>
          </div>

        </div>
      )}

      {mode !== "manual" && (
        <div className="bg-[var(--background)] border border-[var(--border-color)] p-12 shadow-sm text-center mb-8">
          <UploadCloud className="w-12 h-12 text-brand-slate mx-auto mb-4 opacity-50" />
          <h3 className="text-xl font-serif text-brand-gold mb-2">Automated Upload</h3>
          <p className="text-sm text-brand-slate mb-6">
            {mode === "pdf" ? "Select a broker contract note PDF to parse." : "Select a CSV/Excel ledger to import."}
          </p>
          {mode === "pdf" ? (
            <>
              <input 
                type="file" 
                id="pdf-file-upload" 
                accept="application/pdf"
                onChange={handlePdfUpload}
                className="hidden"
              />
              <label 
                htmlFor="pdf-file-upload"
                className="inline-block cursor-pointer bg-transparent border border-[var(--border-color)] text-[var(--foreground)] hover:border-brand-gold transition-colors px-6 py-2 uppercase text-xs tracking-wider font-semibold"
              >
                {isUploading ? "Uploading & Parsing..." : "Select PDF File"}
              </label>
            </>
          ) : (
            <>
              <input 
                type="file" 
                id="csv-file-upload" 
                accept=".csv, .xls, .xlsx"
                onChange={handleSpreadsheetUpload}
                className="hidden"
              />
              <label 
                htmlFor="csv-file-upload"
                className="inline-block cursor-pointer bg-transparent border border-[var(--border-color)] text-[var(--foreground)] hover:border-brand-gold transition-colors px-6 py-2 uppercase text-xs tracking-wider font-semibold"
              >
                {isUploading ? "Uploading & Parsing..." : "Select CSV/Excel File"}
              </label>
            </>
          )}
          <div className="mt-8 pt-8 border-t border-[var(--border-color)] text-xs text-brand-slate">
            {mode === "pdf" ? "Supports standard contract notes (PDF)." : "Supports Excel/CSV ledgers. Ensure column headers are present."}
          </div>
        </div>
      )}

      {/* Current Ledger View */}
      <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm mt-8">
        <h3 className="text-lg font-serif text-brand-gold mb-2 border-b border-[var(--border-color)] pb-2">
          Current Ledger: <span className="text-[var(--foreground)]">{account}</span>
        </h3>
        <p className="text-xs text-brand-slate mb-6">Use this to view your current ledger and remove any incorrectly entered transactions. Deletions are permanent.</p>

        {isLoadingLedger ? (
          <div className="text-center p-8 text-brand-slate text-sm">Loading ledger...</div>
        ) : ledger.length === 0 ? (
          <div className="text-center p-8 text-brand-slate text-sm">Ledger is empty.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[var(--border-color)] bg-[var(--hover-bg)]">
                  <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold w-12">#</th>
                  <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold">Date</th>
                  <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold">Details</th>
                  <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold text-right">Amount</th>
                  <th className="p-3 text-[10px] uppercase tracking-wider text-brand-slate font-semibold w-24 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {ledger.map((row, idx) => {
                  const isRich = "Action" in row && "Asset Name" in row;
                  const details = isRich ? `${row.Action}: ${row["Asset Name"]}` : row.Details;
                  
                  let amt = "";
                  if (isRich) {
                    amt = formatAmount(Number(row["Net Amount"]));
                  } else {
                    const paid = Number(row["Paid In"] || 0);
                    const withd = Number(row["Withdrawn"] || 0);
                    amt = formatAmount(paid !== 0 ? paid : withd);
                  }

                  return (
                    <tr key={idx} className="border-b border-[var(--border-color)] hover:bg-[var(--hover-bg)] transition-colors text-sm">
                      <td className="p-3 text-brand-slate text-xs">{idx}</td>
                      <td className="p-3 text-[var(--foreground)]">{row.Date}</td>
                      <td className="p-3 text-[var(--foreground)] truncate max-w-xs">{details}</td>
                      <td className="p-3 text-[var(--foreground)] font-mono text-right">{amt}</td>
                      <td className="p-3 text-right">
                        {pendingDelete === idx ? (
                          <div className="flex gap-2 justify-end">
                            <button onClick={() => handleDeleteRow(idx)} className="text-brand-red hover:text-brand-red/80 font-bold" title="Confirm Delete">✅</button>
                            <button onClick={() => setPendingDelete(null)} className="text-brand-slate hover:text-white" title="Cancel">❌</button>
                          </div>
                        ) : (
                          <button onClick={() => setPendingDelete(idx)} className="text-brand-slate hover:text-brand-red transition-colors" title="Delete Row">
                            <Trash2 className="w-4 h-4 inline" />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
}
