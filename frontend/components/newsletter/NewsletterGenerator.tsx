"use client";

import React, { useState, useEffect } from "react";
import { Mail, Clock, FileText, Settings, Send, Play, FileCheck } from "lucide-react";
import { NewsletterProduct, NewsletterProductSchedule, SnapshotMeta } from "@/types";

export function NewsletterGenerator() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const [products, setProducts] = useState<NewsletterProduct[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<NewsletterProduct | null>(null);
  
  const [availableAccounts, setAvailableAccounts] = useState<string[]>([]);
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([]);
  const [availableBenchmarks, setAvailableBenchmarks] = useState<string[]>([]);
  
  const [snapshots, setSnapshots] = useState<SnapshotMeta[]>([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState<string>("auto");
  
  const [promptPreview, setPromptPreview] = useState("");
  const [isGeneratingPrompt, setIsGeneratingPrompt] = useState(false);
  
  const [htmlContent, setHtmlContent] = useState("");
  const [isGeneratingHtml, setIsGeneratingHtml] = useState(false);
  
  const [isSending, setIsSending] = useState(false);
  const [isGeneratingAndSend, setIsGeneratingAndSend] = useState(false);
  const [message, setMessage] = useState({ text: "", type: "" });
  const [scheduleMessage, setScheduleMessage] = useState<{ text: string; type: string } | null>(null);
  
  const [scheduleCfg, setScheduleCfg] = useState<NewsletterProductSchedule>({
    day: "Saturday",
    hour: 8,
    minute: 0,
    enabled: false,
    refresh_hours: 2,
    additional_recipients: ""
  });

  useEffect(() => {
    fetchProducts();
    fetchAccounts();
    fetchSnapshots();
    fetchBenchmarks();
  }, []);

  const fetchBenchmarks = async () => {
    try {
      const res = await fetch(`${API_URL}/api/system/benchmarks`);
      const data = await res.json();
      if (data.benchmarks) {
        setAvailableBenchmarks(data.benchmarks.map((b: { name: string }) => b.name));
      }
    } catch (e) {
      console.error("Failed to fetch available benchmarks", e);
    }
  };

  const fetchSnapshots = async () => {
    try {
      const res = await fetch(`${API_URL}/api/newsletter/snapshots`);
      const data = await res.json();
      setSnapshots(data.snapshots || []);
    } catch (e) {
      console.error("Failed to fetch snapshots", e);
    }
  };

  const fetchProducts = async () => {
    try {
      const res = await fetch(`${API_URL}/api/newsletter/products`);
      const data = await res.json();
      setProducts(data.products || []);
      if (data.products && data.products.length > 0) {
        selectProduct(data.products[0]);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchAccounts = async () => {
    try {
      const res = await fetch(`${API_URL}/api/ingestion/accounts`);
      const data = await res.json();
      if (data.accounts) {
        const formatted = data.accounts.map((a: string | { name: string }) => 
          typeof a === "string" ? a : a.name
        );
        const filtered = formatted.filter((a: string) => a !== "Consolidated");
        setAvailableAccounts(filtered);
      }
    } catch (e) {
      console.error("Failed to fetch available accounts", e);
    }
  };

  const selectProduct = (p: NewsletterProduct) => {
    setSelectedProduct(p);
    setSelectedAccounts(p.accounts || []);
    setScheduleCfg({
      day: p.schedule?.day || "Saturday",
      hour: p.schedule?.hour || 8,
      minute: p.schedule?.minute || 0,
      enabled: p.schedule?.enabled || false,
      refresh_hours: p.schedule?.refresh_hours || 2,
      additional_recipients: (p.recipients || []).join(", ")
    });
  };

  const handleAccountToggle = async (accountName: string) => {
    if (!selectedProduct) return;
    let updated: string[];
    if (selectedAccounts.includes(accountName)) {
      updated = selectedAccounts.filter(a => a !== accountName);
    } else {
      updated = [...selectedAccounts, accountName];
    }
    setSelectedAccounts(updated);
    
    const updatedProduct = { ...selectedProduct, accounts: updated };
    setSelectedProduct(updatedProduct);
    
    try {
      await fetch(`${API_URL}/api/newsletter/update-accounts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: selectedProduct.product_id,
          accounts: updated
        })
      });
      setProducts(prev => prev.map(prod => 
        prod.product_id === selectedProduct.product_id 
          ? { ...prod, accounts: updated } 
          : prod
      ));
    } catch (err) {
      console.error("Failed to update product accounts", err);
    }
  };

  const handleSyntheticBenchmarkChange = async (benchmarkName: string) => {
    if (!selectedProduct) return;
    const updatedProduct = { ...selectedProduct, synthetic_benchmark: benchmarkName };
    setSelectedProduct(updatedProduct);

    try {
      await fetch(`${API_URL}/api/newsletter/update-product-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: selectedProduct.product_id,
          synthetic_benchmark: benchmarkName
        })
      });
      setProducts(prev => prev.map(prod => 
        prod.product_id === selectedProduct.product_id 
          ? { ...prod, synthetic_benchmark: benchmarkName } 
          : prod
      ));
    } catch (err) {
      console.error("Failed to update product synthetic benchmark", err);
    }
  };

  const handlePreviewPrompt = async () => {
    if (!selectedProduct) return;
    setIsGeneratingPrompt(true);
    setMessage({ text: "", type: "" });
    try {
      const res = await fetch(`${API_URL}/api/newsletter/preview-prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product: selectedProduct,
          accounts: selectedAccounts,
          chosen_folder: selectedSnapshot
        })
      });
      const data = await res.json();
      if (res.ok) {
        setPromptPreview(data.prompt);
        setMessage({ text: `Prompt preview ready! Featured: ${data.featured_ticker}`, type: "success" });
      } else {
        setMessage({ text: data.detail || "Failed to preview prompt", type: "error" });
      }
    } catch (e: any) {
      setMessage({ text: e.message, type: "error" });
    } finally {
      setIsGeneratingPrompt(false);
    }
  };

  const handleGenerateHtml = async () => {
    if (!selectedProduct) return;
    setIsGeneratingHtml(true);
    setHtmlContent("");
    setMessage({ text: "", type: "" });
    try {
      const res = await fetch(`${API_URL}/api/newsletter/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product: selectedProduct,
          accounts: selectedAccounts,
          chosen_folder: selectedSnapshot
        })
      });
      const data = await res.json();
      if (res.ok) {
        setHtmlContent(data.html);
        setMessage({ text: "Newsletter generated successfully!", type: "success" });
      } else {
        setMessage({ text: data.detail || "Failed to generate newsletter", type: "error" });
      }
    } catch (e: any) {
      setMessage({ text: e.message, type: "error" });
    } finally {
      setIsGeneratingHtml(false);
    }
  };

  const handleSendEmail = async () => {
    if (!htmlContent || !selectedProduct) return;
    setIsSending(true);
    setMessage({ text: "", type: "" });
    try {
      const res = await fetch(`${API_URL}/api/newsletter/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          html: htmlContent,
          subject: selectedProduct.subject_template || "Weekly Investor Letter",
          recipients: selectedProduct.recipients || []
        })
      });
      if (res.ok) {
        setMessage({ text: "Email sent successfully!", type: "success" });
      } else {
        const d = await res.json();
        setMessage({ text: d.detail || "Failed to send email", type: "error" });
      }
    } catch (e: any) {
      setMessage({ text: e.message, type: "error" });
    } finally {
      setIsSending(false);
    }
  };

  const handleGenerateAndSend = async () => {
    if (!selectedProduct) return;
    setIsGeneratingAndSend(true);
    setMessage({ text: "", type: "" });
    try {
      const res = await fetch(`${API_URL}/api/newsletter/generate-and-send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product: selectedProduct,
          accounts: selectedAccounts,
          chosen_folder: selectedSnapshot
        })
      });
      if (res.ok) {
        setMessage({ text: "Newsletter generated and sent successfully!", type: "success" });
      } else {
        const data = await res.json();
        setMessage({ text: data.detail || "Failed to generate and send newsletter", type: "error" });
      }
    } catch (e: any) {
      setMessage({ text: e.message, type: "error" });
    } finally {
      setIsGeneratingAndSend(false);
    }
  };

  const handleSaveSchedule = async () => {
    if (!selectedProduct) return;
    setScheduleMessage(null);
    try {
      const recips = scheduleCfg.additional_recipients.split(",").map((s: string) => s.trim()).filter(Boolean);
      const res = await fetch(`${API_URL}/api/newsletter/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: selectedProduct.product_id,
          ...scheduleCfg,
          additional_recipients: recips
        })
      });
      if (res.ok) {
        setScheduleMessage({ text: "Schedule updated successfully!", type: "success" });
        setMessage({ text: "Schedule updated successfully!", type: "success" });
        fetchProducts(); // refresh UI
        setTimeout(() => setScheduleMessage(null), 5000);
      } else {
        setScheduleMessage({ text: "Failed to update schedule", type: "error" });
        setMessage({ text: "Failed to update schedule", type: "error" });
      }
    } catch (e: any) {
      setScheduleMessage({ text: e.message, type: "error" });
      setMessage({ text: e.message, type: "error" });
    }
  };

  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex flex-1 h-[calc(100vh-64px)] w-full overflow-hidden bg-[var(--background)] relative">
      {/* ══ COMMAND SIDEBAR ══ */}
      <aside 
        className={`border-r border-[var(--border-color)] bg-[var(--background)] flex flex-col shrink-0 overflow-y-auto transition-all duration-300 ease-in-out z-20 ${
          sidebarOpen ? "w-[260px] translate-x-0" : "w-0 -translate-x-full border-transparent"
        }`}
      >
        <div className="p-4 border-b border-[var(--border-color)] bg-[var(--border-color)]/30">
          <h2 className="text-[10px] uppercase tracking-[0.2em] text-[var(--foreground)] font-semibold flex items-center gap-2">
            <Settings className="w-3 h-3 shrink-0" /> Newsletter Settings
          </h2>
        </div>
        
        <div className="p-4 space-y-8 pb-20">
          {message.text && (
            <div className={`p-3 text-xs border ${message.type === "error" ? "bg-red-900/20 border-red-900/50 text-red-400" : "bg-green-900/20 border-green-900/50 text-green-400"}`}>
              {message.text}
            </div>
          )}

          {/* Product Configuration */}
          <div className="space-y-4">
            <h3 className="text-[13px] font-bold uppercase tracking-wider text-brand-gold border-b border-[var(--border-color)] pb-1 mb-4 flex items-center gap-2">
              <Settings className="w-4 h-4" /> Product Config
            </h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider mb-2">Select Product</label>
                <select 
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-xs text-[var(--foreground)] outline-none focus:border-brand-gold"
                  value={selectedProduct?.product_id || ""}
                  onChange={(e) => {
                    const p = products.find(x => x.product_id === e.target.value);
                    if (p) selectProduct(p);
                  }}
                >
                  {products.map(p => (
                    <option key={p.product_id} value={p.product_id}>{p.product_id}</option>
                  ))}
                </select>
              </div>

              {selectedProduct && (
                <div className="text-xs text-brand-slate space-y-3 mt-4">
                  <p><strong>Language:</strong> {selectedProduct.language === "it" ? "Italian 🇮🇹" : "English 🇬🇧"}</p>
                  <p><strong>Output:</strong> {selectedProduct.output_filename}</p>
                  <p><strong>Last Sent:</strong> {selectedProduct.last_sent || "Never"}</p>
                  
                  <div className="space-y-1.5 pt-2 border-t border-[var(--border-color)]">
                    <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider">Portfolios to Include</label>
                    <div className="flex flex-col gap-1.5 mt-1.5">
                      {availableAccounts.map(acc => {
                        const isChecked = selectedAccounts.includes(acc);
                        return (
                          <label 
                            key={acc}
                            className={`flex items-center gap-2 px-2.5 py-1.5 border text-xs cursor-pointer select-none transition-colors ${
                              isChecked 
                                ? "bg-brand-gold/10 border-brand-gold text-[var(--foreground)]" 
                                : "border-[var(--border-color)] text-brand-slate hover:text-[var(--foreground)]"
                            }`}
                          >
                            <input 
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => handleAccountToggle(acc)}
                              className="accent-brand-gold"
                            />
                            {acc}
                          </label>
                        );
                      })}
                    </div>
                  </div>

                  <div className="space-y-1.5 pt-2 border-t border-[var(--border-color)]">
                    <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider">Synthetic Benchmark</label>
                    <select
                      value={selectedProduct.synthetic_benchmark || "Global 80/20"}
                      onChange={(e) => handleSyntheticBenchmarkChange(e.target.value)}
                      className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-xs text-[var(--foreground)] outline-none focus:border-brand-gold transition-colors"
                    >
                      {availableBenchmarks.length > 0 ? (
                        availableBenchmarks.map(bm => (
                          <option key={bm} value={bm}>{bm}</option>
                        ))
                      ) : (
                        <option value="Global 80/20">Global 80/20</option>
                      )}
                    </select>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Auto-Scheduler */}
          <div className="space-y-4">
            <h3 className="text-[13px] font-bold uppercase tracking-wider text-brand-gold border-b border-[var(--border-color)] pb-1 mb-4 flex items-center gap-2">
              <Clock className="w-4 h-4" /> Auto-Scheduler
            </h3>
            
            {selectedProduct?.last_sent && (
              <div className="text-[11px] text-brand-slate bg-[var(--border-color)]/20 border border-[var(--border-color)] p-2 rounded flex items-center gap-2">
                <Clock className="w-3.5 h-3.5 text-brand-gold shrink-0" />
                <span>Last sent: <strong className="text-[var(--foreground)]">{selectedProduct.last_sent}</strong></span>
              </div>
            )}
            
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-semibold text-[var(--foreground)] uppercase tracking-wider">Enable Scheduler</label>
                <input 
                  type="checkbox" 
                  checked={scheduleCfg.enabled}
                  onChange={(e) => setScheduleCfg({...scheduleCfg, enabled: e.target.checked})}
                  className="w-4 h-4 accent-brand-gold"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider mb-2">Day</label>
                  <select 
                    value={scheduleCfg.day}
                    onChange={(e) => setScheduleCfg({...scheduleCfg, day: e.target.value})}
                    className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-xs text-[var(--foreground)] outline-none focus:border-brand-gold"
                  >
                    {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map(d => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider mb-2">Time (HH:MM)</label>
                  <div className="flex gap-2">
                    <input type="number" min="0" max="23" value={scheduleCfg.hour} onChange={e => setScheduleCfg({...scheduleCfg, hour: parseInt(e.target.value)})} className="w-full bg-transparent border border-[var(--border-color)] p-2 text-xs text-center" />
                    <span className="self-center text-brand-slate">:</span>
                    <input type="number" min="0" max="59" value={scheduleCfg.minute} onChange={e => setScheduleCfg({...scheduleCfg, minute: parseInt(e.target.value)})} className="w-full bg-transparent border border-[var(--border-color)] p-2 text-xs text-center" />
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider mb-2">Refresh Before Send (Hours)</label>
                <input 
                  type="number" 
                  min="1" 
                  max="12" 
                  value={scheduleCfg.refresh_hours} 
                  onChange={(e) => setScheduleCfg({...scheduleCfg, refresh_hours: parseInt(e.target.value)})}
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-xs text-[var(--foreground)] outline-none focus:border-brand-gold"
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider mb-2">Recipients (Comma separated)</label>
                <input 
                  type="text"
                  value={scheduleCfg.additional_recipients}
                  onChange={(e) => setScheduleCfg({...scheduleCfg, additional_recipients: e.target.value})}
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-xs text-[var(--foreground)] outline-none focus:border-brand-gold"
                />
                <p className="text-[10px] text-brand-slate mt-1.5 leading-relaxed">
                  Primary (non-removable): <strong className="text-[var(--foreground)] font-mono select-all">giuseppe.di.vita12@googlemail.com</strong>
                </p>
              </div>

              <button 
                onClick={handleSaveSchedule}
                className="w-full bg-transparent border border-[var(--border-color)] text-[var(--foreground)] hover:border-brand-gold transition-colors p-2 text-xs font-semibold tracking-wider uppercase mt-4"
              >
                Save Schedule
              </button>

              {scheduleMessage && (
                <div className={`p-2.5 text-[11px] border mt-2 text-center rounded ${
                  scheduleMessage.type === "error" 
                    ? "bg-red-900/10 border-red-900/30 text-red-400" 
                    : "bg-green-900/10 border-green-900/30 text-green-400"
                }`}>
                  {scheduleMessage.text}
                </div>
              )}
            </div>
          </div>

          {/* Research Knowledge Bank */}
          <div className="space-y-4">
            <h3 className="text-[13px] font-bold uppercase tracking-wider text-brand-gold border-b border-[var(--border-color)] pb-1 mb-4 flex items-center gap-2">
              <FileCheck className="w-4 h-4" /> Knowledge Bank
            </h3>
            <div className="space-y-4 text-xs text-brand-slate">
              <p>Select the research snapshot folder to use for the PM Digest generation.</p>
              
              <div>
                <label className="block text-[11px] font-semibold text-brand-slate uppercase tracking-wider mb-2">Snapshot Source</label>
                <select 
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] p-2 text-xs text-[var(--foreground)] outline-none focus:border-brand-gold"
                  value={selectedSnapshot}
                  onChange={(e) => setSelectedSnapshot(e.target.value)}
                >
                  <option value="auto">Auto-select active (newest)</option>
                  {snapshots.map(s => (
                    <option key={s.path} value={s.path}>{s.name} ({s.date})</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

        </div>
      </aside>

      {/* Sidebar Toggle Button */}
      <div className="absolute top-4 left-4 z-30">
        {!sidebarOpen && (
          <button 
            onClick={() => setSidebarOpen(true)}
            className="p-2 bg-[var(--background)] border border-[var(--border-color)] rounded-md shadow-sm hover:border-brand-gold transition-colors"
          >
            <Settings className="w-4 h-4 text-brand-slate" />
          </button>
        )}
      </div>

      {/* MAIN CONTENT AREA */}
      <main className="flex-1 overflow-auto bg-[var(--background)] relative">
        {/* HERO BANNER */}
        <div className="w-full h-[200px] border-y-[3px] border-brand-gold relative flex justify-end bg-[var(--background)] shrink-0">
          {sidebarOpen && (
            <button 
              onClick={() => setSidebarOpen(false)}
              className="absolute left-4 top-4 p-2 bg-[var(--background)]/50 backdrop-blur-sm border border-[var(--border-color)] rounded-md shadow-sm hover:border-brand-gold transition-colors z-10"
              title="Close Sidebar"
            >
              <svg className="w-4 h-4 text-brand-slate" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
              </svg>
            </button>
          )}
          <div className="relative w-full max-w-[800px] h-full">
            <img 
              src="/hero.png" 
              alt="Generated Coastal Scene" 
              className="w-full h-full object-cover object-[right_55%]"
            />
            <div className="absolute inset-0 bg-gradient-to-r from-[var(--background)] via-[var(--background)]/60 to-transparent pointer-events-none"></div>
          </div>
        </div>

        {/* CONTENT */}
        <div className="max-w-6xl mx-auto space-y-10 p-8 pb-20">
          {/* Header Title */}
          <div className="-mt-40 relative z-10 mb-16 pointer-events-none">
            <h1 className="text-4xl font-serif text-brand-gold mb-2 drop-shadow-md">
              Investor Newsletter
            </h1>
            <p className="text-sm text-[var(--foreground)] max-w-xl font-light drop-shadow-sm">
              AI-Driven Weekly Digest & Portfolio Insights
            </p>
          </div>

          <div className="pt-16 space-y-6">
            {/* Generate Newsletter Box */}
            <div className="bg-[var(--background)] border border-[var(--border-color)] p-6 shadow-sm flex flex-col items-center justify-center text-center gap-6">
              <h3 className="text-xl font-serif text-brand-gold">Generate Newsletter</h3>
              <p className="text-sm text-brand-slate max-w-md">
                Generates the weekly newsletter for {selectedProduct?.product_id} by pulling portfolio data, fetching technicals, and compiling the Barclays digest.
              </p>
              
              <div className="flex flex-wrap justify-center gap-4 w-full">
                <button 
                  onClick={handlePreviewPrompt}
                  disabled={isGeneratingPrompt || isGeneratingHtml || isSending || isGeneratingAndSend || selectedAccounts.length === 0}
                  className="flex items-center justify-center gap-2 bg-transparent border border-[var(--border-color)] text-[var(--foreground)] hover:border-brand-gold transition-colors px-4 py-2.5 uppercase text-[11px] tracking-wider font-semibold disabled:opacity-50 flex-1 min-w-[140px]"
                >
                  {isGeneratingPrompt ? <Clock className="w-3.5 h-3.5 animate-spin" /> : <FileText className="w-3.5 h-3.5" />}
                  Preview Prompt
                </button>
                
                <button 
                  onClick={handleGenerateHtml}
                  disabled={isGeneratingPrompt || isGeneratingHtml || isSending || isGeneratingAndSend || selectedAccounts.length === 0}
                  className="flex items-center justify-center gap-2 bg-brand-gold text-[var(--background)] hover:bg-[#b58b38] transition-colors px-4 py-2.5 uppercase text-[11px] tracking-wider font-semibold disabled:opacity-50 flex-1 min-w-[140px]"
                >
                  {isGeneratingHtml ? <Clock className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5 fill-current" />}
                  Generate & Render
                </button>

                <button 
                  onClick={handleSendEmail}
                  disabled={!htmlContent || isGeneratingPrompt || isGeneratingHtml || isSending || isGeneratingAndSend}
                  className="flex items-center justify-center gap-2 bg-brand-navy hover:bg-brand-navy-light text-white transition-colors px-4 py-2.5 uppercase text-[11px] tracking-wider font-semibold disabled:opacity-40 flex-1 min-w-[140px]"
                  title={!htmlContent ? "Generate the newsletter first to send it" : "Send email to recipients"}
                >
                  {isSending ? <Clock className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                  Send Email Now
                </button>

                <button 
                  onClick={handleGenerateAndSend}
                  disabled={isGeneratingPrompt || isGeneratingHtml || isSending || isGeneratingAndSend || selectedAccounts.length === 0}
                  className="flex items-center justify-center gap-2 bg-transparent border border-red-500/30 text-red-500 hover:bg-red-500/10 transition-colors px-4 py-2.5 uppercase text-[11px] tracking-wider font-semibold disabled:opacity-50 flex-1 min-w-[140px]"
                  title="Generates and sends the email in one headless run"
                >
                  {isGeneratingAndSend ? <Clock className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                  Generate & Send Now
                </button>
              </div>
            </div>

            {promptPreview && (
              <div className="bg-[#111] border border-[var(--border-color)] p-4 shadow-sm">
                <h4 className="text-xs font-semibold text-brand-slate uppercase tracking-wider mb-2 flex items-center gap-2">
                  <FileCheck className="w-4 h-4" /> Full Gemini Prompt
                </h4>
                <textarea 
                  className="w-full h-64 bg-transparent text-[#00ff00] text-xs font-mono p-2 outline-none border-none resize-y"
                  readOnly
                  value={promptPreview}
                />
              </div>
            )}

            {htmlContent && (
              <div className="bg-white border border-[var(--border-color)] p-0 shadow-sm relative overflow-hidden rounded-md">
                <div className="bg-[var(--background)] border-b border-[var(--border-color)] p-3 flex justify-between items-center">
                  <span className="text-xs font-semibold text-brand-slate uppercase tracking-wider">Preview (Actual Render)</span>
                  <button 
                    onClick={handleSendEmail}
                    disabled={isSending}
                    className="flex items-center gap-2 bg-brand-gold text-[var(--background)] hover:bg-[#b58b38] transition-colors px-4 py-1.5 uppercase text-xs tracking-wider font-semibold disabled:opacity-50"
                  >
                    {isSending ? "Sending..." : "Send Email Now"}
                    <Send className="w-3 h-3" />
                  </button>
                </div>
                <iframe 
                  srcDoc={htmlContent}
                  className="w-full h-[800px] border-none bg-white"
                  title="Newsletter Preview"
                />
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
