"use client";

import React, { useState, useEffect } from "react";
import { TrendingUp, Mail, RefreshCw, Eye, X, Settings2, Clock, Activity as ActivityIcon, BarChart3, ListFilter } from "lucide-react";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function UptrendAlerts() {
  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  const [alertsState, setAlertsState] = useState<Record<string, Record<string, string>>>({});
  const [universe, setUniverse] = useState<{ holdings: string[]; exited: string[]; watchlist: any[] }>({
    holdings: [],
    exited: [],
    watchlist: []
  });
  const [config, setConfig] = useState({ 
    enable_weekly_recap: false,
    recap_day: 4,
    recap_hour: 18,
    threshold_rsi: 55,
    volume_surge_multiplier: 1.5
  });
  const [loading, setLoading] = useState(true);
  const [savingConfig, setSavingConfig] = useState(false);
  const [sendingTest, setSendingTest] = useState(false);
  const [testMessage, setTestMessage] = useState("");
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [resState, resConfig, resUniverse] = await Promise.all([
        fetch(`${API}/api/system/uptrend-alerts-state`),
        fetch(`${API}/api/system/uptrend-alerts-config`),
        fetch(`${API}/api/watchlist/universe`)
      ]);
      if (resState.ok) {
        const data = await resState.json();
        setAlertsState(data);
      }
      if (resConfig.ok) {
        const conf = await resConfig.json();
        setConfig({
          enable_weekly_recap: conf.enable_weekly_recap ?? false,
          recap_day: conf.recap_day ?? 4,
          recap_hour: conf.recap_hour ?? 18,
          threshold_rsi: conf.threshold_rsi ?? 55,
          volume_surge_multiplier: conf.volume_surge_multiplier ?? 1.5
        });
      }
      if (resUniverse.ok) {
        const u = await resUniverse.json();
        setUniverse({
          holdings: u.holdings || [],
          exited: u.exited || [],
          watchlist: u.watchlist || []
        });
      }
    } catch (e) {
      console.error("Failed to load uptrend alerts state", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const updateConfig = async (updates: Partial<typeof config>) => {
    setSavingConfig(true);
    const newConfig = { ...config, ...updates };
    try {
      const res = await fetch(`${API}/api/system/uptrend-alerts-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newConfig)
      });
      if (res.ok) {
        setConfig(newConfig);
      }
    } catch (e) {
      console.error("Failed to save uptrend config", e);
    } finally {
      setSavingConfig(false);
    }
  };

  const sendTestEmail = async () => {
    setSendingTest(true);
    setTestMessage("");
    try {
      const res = await fetch(`${API}/api/system/test-uptrend-alert`, { method: "POST" });
      if (res.ok) {
        setTestMessage("Test uptrend email sent successfully!");
      } else {
        const data = await res.json();
        setTestMessage(`Failed: ${data.detail || res.statusText}`);
      }
    } catch (e: any) {
      setTestMessage(`Failed: ${e.message}`);
    } finally {
      setSendingTest(false);
    }
  };

  const loadPreview = async () => {
    setLoadingPreview(true);
    try {
      const res = await fetch(`${API}/api/system/preview-uptrend-alert`);
      if (res.ok) {
        const data = await res.json();
        setPreviewHtml(data.html);
      }
    } catch (e: any) {
      console.error(e);
    } finally {
      setLoadingPreview(false);
    }
  };

  const hasAlerts = Object.keys(alertsState).length > 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold flex items-center gap-2 text-[var(--foreground)]">
            <TrendingUp className="w-5 h-5 text-emerald-500" />
            Specular Uptrend Alerts
          </h2>
          <p className="text-xs text-[var(--slate)] mt-1">
            Event-driven breakout notifications covering portfolio holdings, exited positions, and watchlist candidates.
          </p>
        </div>
        <button
          onClick={fetchData}
          className="p-2 hover:bg-[var(--card-hover)] rounded-md transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 text-brand-slate ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Monitored Universe Summary */}
      <div className="bg-[var(--card-hover)]/50 rounded-lg p-4 border border-[var(--border-color)]">
        <div className="flex items-center gap-2 mb-3">
          <ListFilter className="w-4 h-4 text-brand-gold" />
          <h3 className="text-sm font-medium text-[var(--foreground)]">Monitored Universe Coverage</h3>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-center">
          <div className="bg-[var(--background)] p-3 rounded border border-[var(--border-color)]">
            <div className="text-xs text-[var(--slate)] uppercase font-semibold">Active Holdings</div>
            <div className="text-lg font-bold text-brand-gold mt-1">{universe.holdings.length}</div>
            <div className="text-[10px] text-[var(--slate)] mt-0.5">Current portfolio positions</div>
          </div>
          <div className="bg-[var(--background)] p-3 rounded border border-[var(--border-color)]">
            <div className="text-xs text-[var(--slate)] uppercase font-semibold">Auto-Included Exits</div>
            <div className="text-lg font-bold text-sky-400 mt-1">{universe.exited.length}</div>
            <div className="text-[10px] text-[var(--slate)] mt-0.5">Sold in last 12 months</div>
          </div>
          <div className="bg-[var(--background)] p-3 rounded border border-[var(--border-color)]">
            <div className="text-xs text-[var(--slate)] uppercase font-semibold">Custom Watchlist</div>
            <div className="text-lg font-bold text-emerald-400 mt-1">{universe.watchlist.length}</div>
            <div className="text-[10px] text-[var(--slate)] mt-0.5">Candidate tickers</div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Detection Thresholds */}
        <div className="bg-[var(--card-hover)] rounded-lg p-4 border border-[var(--border-color)]">
          <h3 className="text-sm font-medium text-[var(--foreground)] mb-4 flex items-center gap-2">
            <Settings2 className="w-4 h-4 text-emerald-500" />
            Detection Thresholds
          </h3>
          <ul className="text-xs text-[var(--slate)] list-disc pl-5 space-y-2 mb-4">
            <li><strong>Golden Cross:</strong> 50-day SMA rises above 200-day SMA</li>
            <li><strong>MACD:</strong> Bullish Crossover</li>
            <li><strong>Composite:</strong> RSI &gt; {config.threshold_rsi} &amp; rising AND Price &gt; 50-day SMA</li>
            <li><strong>Volume Surge:</strong> Volume &ge; {config.volume_surge_multiplier}x 20-day average</li>
          </ul>
          
          <div className="space-y-4 pt-3 border-t border-[var(--border-color)]">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ActivityIcon className="w-4 h-4 text-brand-slate" />
                <span className="text-xs font-medium text-[var(--foreground)]">RSI Breakout Threshold</span>
              </div>
              <div className="flex items-center gap-2">
                <input 
                  type="range" 
                  min="50" max="70" step="1"
                  value={config.threshold_rsi}
                  onChange={(e) => updateConfig({ threshold_rsi: parseInt(e.target.value) })}
                  className="w-24 accent-emerald-500"
                  disabled={savingConfig || loading}
                />
                <span className="text-xs font-semibold text-emerald-500 w-6 text-right">{config.threshold_rsi}</span>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-brand-slate" />
                <span className="text-xs font-medium text-[var(--foreground)]">Volume Surge Multiplier</span>
              </div>
              <div className="flex items-center gap-2">
                <input 
                  type="range" 
                  min="1.2" max="2.5" step="0.1"
                  value={config.volume_surge_multiplier}
                  onChange={(e) => updateConfig({ volume_surge_multiplier: parseFloat(e.target.value) })}
                  className="w-24 accent-emerald-500"
                  disabled={savingConfig || loading}
                />
                <span className="text-xs font-semibold text-emerald-500 w-8 text-right">{config.volume_surge_multiplier.toFixed(1)}x</span>
              </div>
            </div>
          </div>
        </div>

        {/* Schedule & Controls */}
        <div className="bg-[var(--card-hover)] rounded-lg p-4 border border-[var(--border-color)] flex flex-col justify-start">
          <h3 className="text-sm font-medium text-[var(--foreground)] mb-4 flex items-center gap-2">
            <Clock className="w-4 h-4 text-brand-gold" />
            Dispatch Schedule
          </h3>
          <div className="space-y-4">
            <div>
              <div className="text-xs font-semibold text-emerald-500 uppercase tracking-wider mb-1">Event-Driven Alerts</div>
              <p className="text-xs text-[var(--slate)] leading-relaxed">
                Evaluated nightly at 01:00 AM. Emails are dispatched <strong>only</strong> when brand-new signals trigger. Active signals are remembered in state and will not re-alert unless the condition resets.
              </p>
            </div>

            <div className="pt-3 border-t border-[var(--border-color)]">
              <label className="flex items-center justify-between cursor-pointer">
                <div>
                  <div className="text-sm font-medium text-[var(--foreground)]">Weekly Bullish Recap</div>
                  <div className="text-xs text-[var(--slate)] mt-0.5">Digest of all active uptrend postures.</div>
                </div>
                <div className="relative">
                  <input 
                    type="checkbox" 
                    className="sr-only" 
                    checked={config.enable_weekly_recap}
                    onChange={(e) => updateConfig({ enable_weekly_recap: e.target.checked })}
                    disabled={savingConfig || loading}
                  />
                  <div className={`block w-10 h-6 rounded-full transition-colors ${config.enable_weekly_recap ? 'bg-emerald-500' : 'bg-gray-400'}`}></div>
                  <div className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${config.enable_weekly_recap ? 'transform translate-x-4' : ''}`}></div>
                </div>
              </label>

              {config.enable_weekly_recap && (
                <div className="mt-3 pt-3 border-t border-[var(--border-color)] flex items-center justify-between">
                  <span className="text-xs font-medium text-[var(--foreground)]">Recap Time</span>
                  <div className="flex items-center gap-2">
                    <select 
                      value={config.recap_day}
                      onChange={(e) => updateConfig({ recap_day: parseInt(e.target.value) })}
                      disabled={savingConfig || loading}
                      className="text-xs bg-[var(--background)] border border-[var(--border-color)] text-[var(--foreground)] rounded px-2 py-1 outline-none focus:border-emerald-500"
                    >
                      {DAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                    </select>
                    <select 
                      value={config.recap_hour}
                      onChange={(e) => updateConfig({ recap_hour: parseInt(e.target.value) })}
                      disabled={savingConfig || loading}
                      className="text-xs bg-[var(--background)] border border-[var(--border-color)] text-[var(--foreground)] rounded px-2 py-1 outline-none focus:border-emerald-500"
                    >
                      {Array.from({length: 24}).map((_, i) => (
                        <option key={i} value={i}>{i.toString().padStart(2, '0')}:00</option>
                      ))}
                    </select>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Active Uptrend State */}
      <div>
        <h3 className="text-sm font-medium text-[var(--foreground)] mb-3">Active Bullish Postures (Remembered in State)</h3>
        {loading ? (
          <p className="text-sm text-[var(--slate)]">Loading state...</p>
        ) : !hasAlerts ? (
          <p className="text-sm text-[var(--slate)] italic">No active uptrend signals currently stored in state.</p>
        ) : (
          <div className="space-y-4">
            {Object.entries(alertsState).map(([ticker, signals]) => (
              <div key={ticker} className="bg-[var(--background)] p-4 rounded-lg border border-[var(--border-color)]">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-semibold text-emerald-500">{ticker}</span>
                </div>
                <div className="space-y-2 pl-2 border-l-2 border-emerald-500/30">
                  {Object.entries(signals).map(([sigName, timestamp]) => {
                    let dtStr = timestamp as string;
                    try {
                      const dt = new Date(timestamp as string);
                      if (!isNaN(dt.getTime())) {
                        dtStr = dt.toLocaleString(undefined, { 
                          month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' 
                        });
                      }
                    } catch (e) {}
                    return (
                      <div key={sigName} className="flex justify-between items-center text-sm">
                        <span className="text-[var(--foreground)]">{sigName}</span>
                        <span className="text-[var(--slate)] text-xs bg-[var(--card-bg)] px-2 py-1 rounded">{dtStr}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Action Buttons */}
      <div className="pt-6 border-t border-[var(--border-color)]">
        <div className="flex items-center gap-4">
          <button
            onClick={sendTestEmail}
            disabled={sendingTest}
            className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-md text-sm font-medium transition-colors disabled:opacity-50"
          >
            <Mail className="w-4 h-4" />
            {sendingTest ? "Sending..." : "Send Test Uptrend Alert"}
          </button>

          <button
            onClick={loadPreview}
            disabled={loadingPreview}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--card-hover)] hover:bg-[var(--border-color)] text-[var(--foreground)] rounded-md text-sm font-medium transition-colors border border-[var(--border-color)]"
          >
            <Eye className="w-4 h-4 text-emerald-500" />
            {loadingPreview ? "Loading..." : "Preview Email"}
          </button>
        </div>

        {testMessage && (
          <p className={`mt-3 text-sm ${testMessage.startsWith("Test") ? "text-emerald-500" : "text-red-400"}`}>
            {testMessage}
          </p>
        )}
      </div>

      {/* Preview Modal */}
      {previewHtml && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl w-full max-w-4xl h-[85vh] flex flex-col shadow-2xl">
            <div className="p-4 border-b border-[var(--border-color)] flex items-center justify-between">
              <h3 className="font-semibold text-lg flex items-center gap-2 text-[var(--foreground)]">
                <TrendingUp className="w-5 h-5 text-emerald-500" />
                Uptrend Alert Email Preview
              </h3>
              <button
                onClick={() => setPreviewHtml(null)}
                className="p-1 hover:bg-[var(--card-hover)] rounded-md transition-colors text-[var(--slate)]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-hidden p-2 bg-[#e0dbd2]">
              <iframe
                srcDoc={previewHtml}
                title="Email Preview"
                className="w-full h-full border-0 rounded"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
