"use client";

import React, { useState, useEffect } from "react";
import { Bell, Mail, RefreshCw, Eye, X, Settings2, Clock, Activity as ActivityIcon } from "lucide-react";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function DowntrendAlerts() {
  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  const [alertsState, setAlertsState] = useState<Record<string, Record<string, string>>>({});
  const [config, setConfig] = useState({ 
    enable_weekly_recap: true,
    recap_day: 4,
    recap_hour: 18,
    threshold_rsi: 45
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
      const [resState, resConfig] = await Promise.all([
        fetch(`${API}/api/system/alerts-state`),
        fetch(`${API}/api/system/alerts-config`)
      ]);
      if (resState.ok) {
        const data = await resState.json();
        setAlertsState(data);
      }
      if (resConfig.ok) {
        const conf = await resConfig.json();
        setConfig({
          enable_weekly_recap: conf.enable_weekly_recap ?? true,
          recap_day: conf.recap_day ?? 4,
          recap_hour: conf.recap_hour ?? 18,
          threshold_rsi: conf.threshold_rsi ?? 45
        });
      }
    } catch (e) {
      console.error("Failed to load alerts state", e);
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
      const res = await fetch(`${API}/api/system/alerts-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newConfig)
      });
      if (res.ok) {
        setConfig(newConfig);
      }
    } catch (e) {
      console.error("Failed to save config", e);
    } finally {
      setSavingConfig(false);
    }
  };

  const sendTestEmail = async () => {
    setSendingTest(true);
    setTestMessage("");
    try {
      const res = await fetch(`${API}/api/system/test-alert`, { method: "POST" });
      if (res.ok) {
        setTestMessage("Test email sent successfully!");
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
      const res = await fetch(`${API}/api/system/preview-alert`);
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
        <h2 className="text-xl font-semibold flex items-center gap-2 text-[var(--foreground)]">
          <Bell className="w-5 h-5 text-brand-gold" />
          Downtrend Alerts
        </h2>
        <button
          onClick={fetchData}
          className="p-2 hover:bg-[var(--card-hover)] rounded-md transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 text-brand-slate ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Thresholds */}
        <div className="bg-[var(--card-hover)] rounded-lg p-4 border border-[var(--border-color)]">
          <h3 className="text-sm font-medium text-[var(--foreground)] mb-4 flex items-center gap-2">
            <Settings2 className="w-4 h-4 text-brand-gold" />
            Detection Thresholds
          </h3>
          <ul className="text-xs text-[var(--slate)] list-disc pl-5 space-y-2 mb-4">
            <li><strong>Death Cross:</strong> 50-day SMA falls below 200-day SMA</li>
            <li><strong>MACD:</strong> Bearish Crossover</li>
            <li><strong>Composite:</strong> RSI &lt; {config.threshold_rsi} &amp; decreasing AND Price &lt; 50-day SMA</li>
          </ul>
          
          <div className="mt-4 pt-4 border-t border-[var(--border-color)] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ActivityIcon className="w-4 h-4 text-brand-slate" />
              <span className="text-xs font-medium text-[var(--foreground)]">RSI Threshold</span>
            </div>
            <div className="flex items-center gap-2">
              <input 
                type="range" 
                min="20" max="60" step="1"
                value={config.threshold_rsi}
                onChange={(e) => updateConfig({ threshold_rsi: parseInt(e.target.value) })}
                className="w-24 accent-brand-gold"
                disabled={savingConfig || loading}
              />
              <span className="text-xs font-semibold text-brand-gold w-6 text-right">{config.threshold_rsi}</span>
            </div>
          </div>
        </div>

        {/* Feature Controls */}
        <div className="bg-[var(--card-hover)] rounded-lg p-4 border border-[var(--border-color)] flex flex-col justify-start">
          <h3 className="text-sm font-medium text-[var(--foreground)] mb-4 flex items-center gap-2">
            <Clock className="w-4 h-4 text-brand-gold" />
            Schedule & Features
          </h3>
          <div className="space-y-4">
            <label className="flex items-center justify-between cursor-pointer">
              <div>
                <div className="text-sm font-medium text-[var(--foreground)]">Weekly Recap Email</div>
                <div className="text-xs text-[var(--slate)] mt-0.5">Summary of currently active downtrends.</div>
              </div>
              <div className="relative">
                <input 
                  type="checkbox" 
                  className="sr-only" 
                  checked={config.enable_weekly_recap}
                  onChange={(e) => updateConfig({ enable_weekly_recap: e.target.checked })}
                  disabled={savingConfig || loading}
                />
                <div className={`block w-10 h-6 rounded-full transition-colors ${config.enable_weekly_recap ? 'bg-green-500' : 'bg-gray-400'}`}></div>
                <div className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${config.enable_weekly_recap ? 'transform translate-x-4' : ''}`}></div>
              </div>
            </label>

            {config.enable_weekly_recap && (
              <div className="pt-3 border-t border-[var(--border-color)] flex items-center justify-between">
                <span className="text-xs font-medium text-[var(--foreground)]">Dispatch Schedule</span>
                <div className="flex items-center gap-2">
                  <select 
                    value={config.recap_day}
                    onChange={(e) => updateConfig({ recap_day: parseInt(e.target.value) })}
                    disabled={savingConfig || loading}
                    className="text-xs bg-[var(--background)] border border-[var(--border-color)] text-[var(--foreground)] rounded px-2 py-1 outline-none focus:border-brand-gold"
                  >
                    {DAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                  </select>
                  <select 
                    value={config.recap_hour}
                    onChange={(e) => updateConfig({ recap_hour: parseInt(e.target.value) })}
                    disabled={savingConfig || loading}
                    className="text-xs bg-[var(--background)] border border-[var(--border-color)] text-[var(--foreground)] rounded px-2 py-1 outline-none focus:border-brand-gold"
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

      <div>
        <h3 className="text-sm font-medium text-[var(--foreground)] mb-3">Recent Activity</h3>
        {loading ? (
          <p className="text-sm text-[var(--slate)]">Loading...</p>
        ) : !hasAlerts ? (
          <p className="text-sm text-[var(--slate)] italic">No active downtrends detected.</p>
        ) : (
          <div className="space-y-4">
            {Object.entries(alertsState).map(([ticker, signals]) => (
              <div key={ticker} className="bg-[var(--background)] p-4 rounded-lg border border-[var(--border-color)]">
                <div className="font-semibold text-brand-gold mb-2">{ticker}</div>
                <div className="space-y-2 pl-2 border-l-2 border-[var(--border-color)]">
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

      <div className="pt-6 border-t border-[var(--border-color)]">
        <div className="flex items-center gap-4">
          <button
            onClick={sendTestEmail}
            disabled={sendingTest}
            className="flex items-center gap-2 px-4 py-2 bg-brand-gold text-black rounded-lg text-sm font-medium hover:bg-[#e8c37d] transition-colors disabled:opacity-50"
          >
            <Mail className="w-4 h-4" />
            {sendingTest ? "Sending..." : "Send Test Email"}
          </button>
          <button
            onClick={loadPreview}
            disabled={loadingPreview}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--card-bg)] text-[var(--foreground)] border border-[var(--border-color)] rounded-lg text-sm font-medium hover:bg-[var(--card-hover)] transition-colors disabled:opacity-50"
          >
            <Eye className="w-4 h-4" />
            {loadingPreview ? "Loading..." : "Preview Alert Email"}
          </button>
          
          {testMessage && (
            <span className={`text-sm ${testMessage.includes("success") ? "text-green-500" : "text-red-500"}`}>
              {testMessage}
            </span>
          )}
        </div>
      </div>

      {previewHtml && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-white rounded-xl overflow-hidden shadow-2xl w-full max-w-4xl h-[90vh] flex flex-col">
            <div className="flex justify-between items-center p-4 bg-gray-100 border-b border-gray-200">
              <h3 className="font-semibold text-gray-800 flex items-center gap-2">
                <Mail className="w-4 h-4" /> Email Preview
              </h3>
              <button 
                onClick={() => setPreviewHtml(null)}
                className="p-1 hover:bg-gray-200 rounded text-gray-500 hover:text-gray-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-hidden bg-gray-50 flex justify-center p-4">
               <div className="w-[720px] max-w-full h-full bg-white shadow-md overflow-hidden">
                 <iframe 
                   srcDoc={previewHtml} 
                   className="w-full h-full border-0"
                   title="Email Preview"
                 />
               </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
