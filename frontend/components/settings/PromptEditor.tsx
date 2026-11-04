"use client";

import React, { useState, useEffect, useRef } from "react";
import { Edit2, Eye, Save, RefreshCw, FileText, CheckCircle2, AlertCircle, Info } from "lucide-react";

const MOCK_PREVIEW_DATA: Record<string, string> = {
  ticker: "AAPL",
  longName: "Apple Inc.",
  price: "172.50",
  currency: "USD",
  one_year_return: "+14.20%",
  high_52: "199.62",
  low_52: "164.08",
  trend: "Downtrend (50 SMA < 200 SMA)",
  trailing_pe: "28.5",
  forward_pe: "26.1",
  dividend_yield: "0.56%",
  market_cap: "2.71B",
  industry: "Consumer Electronics",
  max_drawdown: "-12.45%",
  expense_ratio: "0.07%",
  aum: "14.25B",
  average_volume: "250K",
  beta: "1.00",
  ret_1w: "-1.25%",
  ret_1m: "+3.50%",
  ret_1y: "+22.40%",
  constituents: `\n- Microsoft Corp. (Weight: 8.50%)\n- Apple Inc. (Weight: 7.20%)\n- NVIDIA Corp. (Weight: 6.80%)\n- Amazon.com Inc. (Weight: 4.10%)\n- Meta Platforms (Weight: 3.20%)`
};

const PROMPT_LABELS: Record<string, string> = {
  deep_dive_stock: "Deep Dive (Stock)",
  deep_dive_etf: "Deep Dive (ETF)",
  market_intel_default: "Market Intelligence (Default)",
  market_intel_macro: "Market Intelligence (Macro-Only)"
};

export function PromptEditor() {
  const [activePromptKey, setActivePromptKey] = useState<string>("deep_dive_stock");
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [defaults, setDefaults] = useState<Record<string, string>>({});
  const [placeholders, setPlaceholders] = useState<Record<string, string[]>>({});
  
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");
  
  const [activeSubTab, setActiveSubTab] = useState<"editor" | "preview">("editor");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    fetchPrompts();
  }, []);

  const fetchPrompts = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/system/prompts`);
      if (!res.ok) throw new Error("Failed to load prompt templates");
      const data = await res.json();
      setPrompts(data.active || {});
      setDefaults(data.defaults || {});
      setPlaceholders(data.placeholders || {});
    } catch (err: any) {
      console.error(err);
      setStatus("error");
      setErrorMessage(err.message || "Failed to connect to backend");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    setStatus("idle");
    setErrorMessage("");
    try {
      const res = await fetch(`${API_URL}/api/system/prompts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompts }),
      });
      
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to update prompt templates");
      }
      
      setStatus("success");
      setTimeout(() => setStatus("idle"), 3000);
    } catch (err: any) {
      console.error(err);
      setStatus("error");
      setErrorMessage(err.message || "An error occurred while saving");
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = async (all = false) => {
    if (!window.confirm(all ? "Are you sure you want to reset ALL prompts to defaults?" : `Are you sure you want to reset the ${PROMPT_LABELS[activePromptKey]} prompt to defaults?`)) {
      return;
    }
    
    setIsResetting(true);
    setStatus("idle");
    setErrorMessage("");
    try {
      const res = await fetch(`${API_URL}/api/system/prompts/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(all ? {} : { prompt_key: activePromptKey }),
      });
      
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to reset prompts");
      }
      
      if (all) {
        setPrompts({ ...defaults });
      } else {
        setPrompts(prev => ({
          ...prev,
          [activePromptKey]: defaults[activePromptKey]
        }));
      }
      
      setStatus("success");
      setTimeout(() => setStatus("idle"), 3000);
    } catch (err: any) {
      console.error(err);
      setStatus("error");
      setErrorMessage(err.message || "An error occurred while resetting");
    } finally {
      setIsResetting(false);
    }
  };

  const handleInsertPlaceholder = (placeholder: string) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = prompts[activePromptKey] || "";
    const insertion = `{{${placeholder}}}`;
    const newText = text.substring(0, start) + insertion + text.substring(end);

    setPrompts(prev => ({
      ...prev,
      [activePromptKey]: newText
    }));

    // Focus back and set cursor range
    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(start + insertion.length, start + insertion.length);
    }, 50);
  };

  const renderPreview = () => {
    const template = prompts[activePromptKey] || "";
    let rendered = template;
    Object.keys(MOCK_PREVIEW_DATA).forEach((key) => {
      rendered = rendered.replace(new RegExp(`\\{\\{\\s*${key}\\s*\\}\\}`, "g"), MOCK_PREVIEW_DATA[key]);
    });
    return rendered;
  };

  if (isLoading) {
    return <div className="text-[var(--slate)] animate-pulse">Loading prompt configuration...</div>;
  }

  const currentPlaceholders = placeholders[activePromptKey] || [];

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-serif text-[var(--foreground)] mb-2">Prompt Templates</h2>
          <p className="text-sm text-[var(--slate)]">
            Customize the system prompt templates sent to Gemini. Valid placeholders are safely replaced with stock/ETF metrics.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => handleReset(false)}
            disabled={isResetting || isSaving}
            className="border border-[var(--border-color)] hover:border-brand-gold text-[var(--foreground)] px-4 py-2 rounded-md text-xs font-semibold uppercase tracking-wider transition-colors disabled:opacity-50"
          >
            Reset Active
          </button>
          <button
            onClick={() => handleReset(true)}
            disabled={isResetting || isSaving}
            className="border border-brand-red/30 hover:border-brand-red text-brand-red px-4 py-2 rounded-md text-xs font-semibold uppercase tracking-wider transition-colors disabled:opacity-50"
          >
            Reset All
          </button>
        </div>
      </div>

      {/* Selector Tabs */}
      <div className="flex border-b border-[var(--border-color)] overflow-x-auto shrink-0 scrollbar-none gap-2">
        {Object.keys(PROMPT_LABELS).map((key) => (
          <button
            key={key}
            onClick={() => {
              setActivePromptKey(key);
              setActiveSubTab("editor");
            }}
            className={`py-3 px-4 text-xs font-semibold uppercase tracking-wider border-b-2 transition-all whitespace-nowrap ${
              activePromptKey === key
                ? "border-brand-gold text-brand-gold font-bold"
                : "border-transparent text-[var(--slate)] hover:text-[var(--foreground)]"
            }`}
          >
            {PROMPT_LABELS[key]}
          </button>
        ))}
      </div>

      {/* Main Content Area */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        
        {/* Placeholders / Variables Sidebar */}
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg p-5">
            <h3 className="text-xs font-bold uppercase tracking-wider text-brand-slate mb-3 flex items-center gap-2">
              <Info className="w-3.5 h-3.5" />
              Available Data
            </h3>
            <p className="text-xs text-[var(--slate)] mb-4 leading-relaxed">
              Click a variable pill below to insert it at your cursor position. These values are computed dynamically.
            </p>
            <div className="flex flex-wrap gap-1.5 max-h-[300px] overflow-y-auto pr-1">
              {currentPlaceholders.map((ph) => (
                <button
                  key={ph}
                  onClick={() => handleInsertPlaceholder(ph)}
                  className="bg-[var(--card-bg)] hover:bg-brand-gold/10 hover:border-brand-gold text-[var(--foreground)] border border-[var(--border-color)] font-mono text-[10px] px-2.5 py-1 rounded transition-colors text-left truncate w-full"
                  title={`Insert {{${ph}}}`}
                >
                  {"{{"}
                  <span className="text-brand-gold">{ph}</span>
                  {"}}"}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Editor and Preview Body */}
        <div className="lg:col-span-3 space-y-4">
          <div className="flex justify-between items-center bg-[var(--background)] border border-[var(--border-color)] rounded-t-lg px-4 py-2">
            <div className="flex gap-2">
              <button
                onClick={() => setActiveSubTab("editor")}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
                  activeSubTab === "editor"
                    ? "bg-brand-navy text-brand-cream"
                    : "text-[var(--slate)] hover:text-[var(--foreground)]"
                }`}
              >
                <Edit2 className="w-3.5 h-3.5" /> Editor
              </button>
              <button
                onClick={() => setActiveSubTab("preview")}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
                  activeSubTab === "preview"
                    ? "bg-brand-navy text-brand-cream"
                    : "text-[var(--slate)] hover:text-[var(--foreground)]"
                }`}
              >
                <Eye className="w-3.5 h-3.5" /> Live Preview
              </button>
            </div>
            <div className="text-[10px] uppercase tracking-widest text-brand-slate font-bold">
              {PROMPT_LABELS[activePromptKey]}
            </div>
          </div>

          <div className="border-x border-b border-[var(--border-color)] bg-[var(--background)] rounded-b-lg p-6 relative">
            
            {activeSubTab === "editor" ? (
              <textarea
                ref={textareaRef}
                value={prompts[activePromptKey] || ""}
                onChange={(e) =>
                  setPrompts({ ...prompts, [activePromptKey]: e.target.value })
                }
                className="w-full h-[450px] bg-[var(--card-bg)] border border-[var(--border-color)] rounded-md p-4 font-mono text-sm leading-relaxed text-[var(--foreground)] focus:outline-none focus:border-brand-gold resize-y"
                placeholder="Enter prompt template here..."
              />
            ) : (
              <div className="w-full h-[450px] bg-[var(--card-bg)] border border-[var(--border-color)] rounded-md p-4 font-mono text-sm leading-relaxed text-[var(--slate)] overflow-auto whitespace-pre-wrap select-text">
                {renderPreview()}
              </div>
            )}

            {/* Notifications / Toast */}
            {status !== "idle" && (
              <div
                className={`mt-4 p-4 rounded-md flex items-start gap-3 border ${
                  status === "success"
                    ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                    : "bg-brand-red/10 border-brand-red/20 text-brand-red"
                }`}
              >
                {status === "success" ? (
                  <>
                    <CheckCircle2 className="w-5 h-5 shrink-0" />
                    <div>
                      <p className="text-sm font-semibold">Changes Saved Successfully</p>
                      <p className="text-xs opacity-80 mt-0.5">The custom template will be used for future generations.</p>
                    </div>
                  </>
                ) : (
                  <>
                    <AlertCircle className="w-5 h-5 shrink-0" />
                    <div>
                      <p className="text-sm font-semibold">Validation / Save Failed</p>
                      <p className="text-xs opacity-80 mt-0.5">{errorMessage}</p>
                    </div>
                  </>
                )}
              </div>
            )}

            <div className="flex justify-end mt-4">
              <button
                onClick={handleSave}
                disabled={isSaving || isResetting}
                className="bg-brand-gold hover:bg-brand-gold-light text-black px-6 py-2.5 rounded-md text-xs font-bold uppercase tracking-wider transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                <Save className="w-4 h-4" />
                {isSaving ? "Saving..." : "Save Template"}
              </button>
            </div>

          </div>
        </div>

      </div>
    </div>
  );
}
