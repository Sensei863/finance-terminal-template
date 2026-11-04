"use client";

import React, { useState } from "react";
import ReactMarkdown from "react-markdown";

interface AIReportPanelProps {
  ticker: string;
  type: "qualitative" | "market-intel";
  onGenerate: () => Promise<string>;
}

export function AIReportPanel({ ticker, type, onGenerate }: AIReportPanelProps) {
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await onGenerate();
      setReport(result);
    } catch (err: any) {
      setError(err.message || "Failed to generate report");
    } finally {
      setLoading(false);
    }
  };

  const title = type === "qualitative" ? "Deep Dive" : "Market Intelligence Report";
  const buttonText = type === "qualitative" ? "Execute Deep Dive" : "Generate Market Intelligence";

  if (report) {
    return (
      <section className="border border-[var(--border-color)] bg-[var(--background)] relative mt-8">
        <div className="absolute top-0 left-0 w-1 h-full bg-brand-gold" />
        <div className="p-4 md:p-6 pl-6 md:pl-8">
          <div className="flex flex-col md:flex-row md:items-center justify-between mb-4 gap-4">
            <h3 className="uppercase text-[10px] tracking-[0.2em] text-brand-slate font-semibold">{title}</h3>
            <button 
              onClick={handleGenerate}
              disabled={loading}
              className="text-[10px] uppercase tracking-widest text-brand-gold hover:text-brand-gold-light transition-colors font-semibold self-start md:self-auto"
            >
              {loading ? "Regenerating..." : "Regenerate"}
            </button>
          </div>
          <div className="font-serif text-base leading-relaxed text-[var(--foreground)] prose prose-sm max-w-none dark:prose-invert prose-headings:text-[var(--foreground)] prose-headings:font-sans prose-a:text-brand-gold">
            <ReactMarkdown>{report}</ReactMarkdown>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="border border-[var(--border-color)] bg-[var(--background)] relative mt-8">
      <div className="absolute top-0 left-0 w-1 h-full bg-brand-gold/30" />
      <div className="p-4 md:p-6 pl-6 md:pl-8 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <h3 className="uppercase text-[10px] tracking-[0.2em] text-brand-slate font-semibold">{title}</h3>
        <button
          onClick={handleGenerate}
          disabled={loading}
          className={`px-6 py-2 text-[10px] font-semibold tracking-wide uppercase flex items-center justify-center gap-2 transition-colors border self-start md:self-auto ${
            loading 
              ? "bg-transparent text-brand-slate border-[var(--border-color)] cursor-not-allowed" 
              : "bg-brand-navy text-brand-cream border-brand-navy hover:bg-brand-navy-light"
          }`}
        >
          {loading ? "Analyzing..." : buttonText}
        </button>
      </div>
      {loading && !report && (
        <div className="px-8 pb-6 space-y-3">
          <div className="h-4 bg-brand-slate/10 rounded animate-pulse w-3/4"></div>
          <div className="h-4 bg-brand-slate/10 rounded animate-pulse w-full"></div>
          <div className="h-4 bg-brand-slate/10 rounded animate-pulse w-5/6"></div>
          <div className="h-4 bg-brand-slate/10 rounded animate-pulse w-1/2 mt-4"></div>
        </div>
      )}
      {error && <p className="text-brand-red text-xs px-8 pb-4">{error}</p>}
    </section>
  );
}
