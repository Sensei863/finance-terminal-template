"use client";

import { useTheme } from "next-themes";
import { Moon, Sun, Search, Filter, TrendingUp, BarChart2 } from "lucide-react";
import { useEffect, useState } from "react";

export default function Home() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <div className="flex flex-col h-screen w-full bg-[var(--background)]">


      {/* ══ MAIN BODY (SPLIT VIEW) ══ */}
      <div className="flex flex-col md:flex-row flex-1 overflow-auto md:overflow-hidden">
        
        {/* ══ COMMAND / INPUT SIDEBAR ══ */}
        <aside className="w-full md:w-72 border-b md:border-r md:border-b-0 border-[var(--border-color)] bg-[var(--background)] flex flex-col shrink-0 overflow-visible md:overflow-y-auto">
          <div className="p-4 border-b border-[var(--border-color)] bg-[var(--border-color)]/30">
            <h2 className="text-[10px] uppercase tracking-[0.2em] text-[var(--foreground)] font-semibold flex items-center gap-2">
              <Search className="w-3 h-3" /> Command Panel
            </h2>
          </div>
          
          <div className="p-4 space-y-6">
            {/* Input Group 1 */}
            <div className="space-y-2">
              <label className="text-[10px] uppercase tracking-wider text-brand-slate font-semibold block">Target Asset / ETF</label>
              <div className="flex">
                <input 
                  type="text" 
                  defaultValue="IUSA.L" 
                  className="w-full bg-[var(--background)] border border-[var(--border-color)] text-[var(--foreground)] text-sm px-3 py-2 outline-none focus:border-brand-gold font-serif"
                />
              </div>
            </div>

            {/* Input Group 2 */}
            <div className="space-y-2">
              <label className="text-[10px] uppercase tracking-wider text-brand-slate font-semibold block">Timeframe</label>
              <select className="w-full bg-[var(--background)] border border-[var(--border-color)] text-[var(--foreground)] text-sm px-3 py-2 outline-none focus:border-brand-gold appearance-none font-sans">
                <option>1 Year (Daily)</option>
                <option>3 Years (Weekly)</option>
                <option>5 Years (Monthly)</option>
              </select>
            </div>

            {/* Actions */}
            <div className="pt-4 border-t border-[var(--border-color)] space-y-3">
              <button className="w-full bg-brand-navy text-brand-cream border border-brand-navy hover:bg-brand-navy-light transition-colors py-2 text-xs font-semibold tracking-wide uppercase flex items-center justify-center gap-2">
                <TrendingUp className="w-4 h-4" /> Execute Deep Dive
              </button>
              <button className="w-full bg-transparent text-[var(--foreground)] border border-[var(--border-color)] hover:border-brand-slate transition-colors py-2 text-xs font-semibold tracking-wide uppercase flex items-center justify-center gap-2">
                <Filter className="w-4 h-4" /> Advanced Filters
              </button>
            </div>
          </div>
        </aside>

        {/* ══ DASHBOARD CONTENT ══ */}
        <main className="flex-1 overflow-auto bg-[var(--background)] relative">
          
          <div className="w-full h-[120px] md:h-[200px] border-y-[3px] border-brand-gold relative flex justify-end bg-[var(--background)]">
            <div className="relative w-full max-w-[800px] h-full">
              <img 
                src="/hero.png" 
                alt="Generated Coastal Scene" 
                className="w-full h-full object-cover object-[right_55%]"
              />
              {/* Gradient fade blending the left side of the image into the background */}
              <div className="absolute inset-0 bg-gradient-to-r from-[var(--background)] via-[var(--background)]/60 to-transparent pointer-events-none"></div>
            </div>
          </div>

          <div className="max-w-5xl mx-auto space-y-8 p-4 md:p-8">
            
            {/* Editorial Narrative Block */}
            <section className="border border-[var(--border-color)] bg-[var(--background)] relative">
              <div className="absolute top-0 left-0 w-1 h-full bg-brand-gold" />
              <div className="p-6 pl-8">
                <h3 className="uppercase text-[10px] tracking-[0.2em] text-brand-slate font-semibold mb-3">AI Market Narrative</h3>
                <p className="font-serif-secondary text-lg italic leading-relaxed text-[var(--foreground)]">
                  The primary narrative this week was the <strong className="font-semibold text-[var(--foreground)]">breakout in US large-cap technology</strong>. Strong earnings revisions across the Magnificent Seven provided the primary catalyst, pushing the target ETF into the upper quartile of its 52-week range.
                </p>
              </div>
            </section>

            {/* Dense Data Table (Traditional Finance style) */}
            <section>
              <div className="flex items-center justify-between mb-3 border-b-2 border-[var(--border-color)] pb-2">
                <h2 className="font-serif text-2xl text-[var(--foreground)] flex items-center gap-2">
                  <BarChart2 className="w-5 h-5 text-brand-gold" /> Component Performance
                </h2>
                <span className="text-[10px] uppercase tracking-widest text-brand-slate">As of Close</span>
              </div>
              
              <div className="border border-[var(--border-color)] overflow-x-auto">
                <table className="w-full text-sm text-right min-w-[400px]">
                  <thead>
                    <tr className="bg-[var(--navy)] text-brand-slate text-[9px] uppercase tracking-widest">
                      <th className="py-2 px-4 text-left font-semibold">Ticker</th>
                      <th className="py-2 px-4 font-semibold">Weight</th>
                      <th className="py-2 px-4 font-semibold">Daily</th>
                      <th className="py-2 px-4 font-semibold">1 Month</th>
                      <th className="py-2 px-4 font-semibold">YTD</th>
                    </tr>
                  </thead>
                  <tbody className="text-[var(--foreground)]">
                    <tr className="border-b border-[var(--border-color)] hover:bg-[var(--border-color)]/20 transition-colors">
                      <td className="py-2 px-4 text-left font-serif font-semibold">AAPL</td>
                      <td className="py-2 px-4 font-mono text-xs">7.24%</td>
                      <td className="py-2 px-4 text-brand-green font-mono text-xs">+1.2%</td>
                      <td className="py-2 px-4 text-brand-green font-mono text-xs">+4.5%</td>
                      <td className="py-2 px-4 text-brand-green font-mono text-xs">+12.1%</td>
                    </tr>
                    <tr className="border-b border-[var(--border-color)] hover:bg-[var(--border-color)]/20 transition-colors">
                      <td className="py-2 px-4 text-left font-serif font-semibold">MSFT</td>
                      <td className="py-2 px-4 font-mono text-xs">6.82%</td>
                      <td className="py-2 px-4 text-brand-green font-mono text-xs">+0.8%</td>
                      <td className="py-2 px-4 text-brand-green font-mono text-xs">+3.2%</td>
                      <td className="py-2 px-4 text-brand-green font-mono text-xs">+9.4%</td>
                    </tr>
                    <tr className="hover:bg-[var(--border-color)]/20 transition-colors">
                      <td className="py-2 px-4 text-left font-serif font-semibold">AMZN</td>
                      <td className="py-2 px-4 font-mono text-xs">3.41%</td>
                      <td className="py-2 px-4 text-brand-red font-mono text-xs">-0.4%</td>
                      <td className="py-2 px-4 text-brand-green font-mono text-xs">+1.8%</td>
                      <td className="py-2 px-4 text-brand-green font-mono text-xs">+7.2%</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

          </div>
        </main>

      </div>
    </div>
  );
}
