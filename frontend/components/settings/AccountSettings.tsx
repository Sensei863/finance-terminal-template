"use client";

import React, { useState, useEffect } from "react";
import { Key, Save, CheckCircle2, AlertCircle } from "lucide-react";

export function AccountSettings() {
  const [apiKey, setApiKey] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    fetchSecrets();
  }, []);

  const fetchSecrets = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/system/secrets`);
      if (!res.ok) throw new Error("Failed to fetch secrets");
      const data = await res.json();
      setApiKey(data.gemini_api_key || "");
    } catch (err) {
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    setStatus("idle");
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/system/secrets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gemini_api_key: apiKey }),
      });
      
      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || "Failed to update API key");
      }
      
      setStatus("success");
      setTimeout(() => setStatus("idle"), 3000);
    } catch (err: any) {
      console.error(err);
      setStatus("error");
      setErrorMessage(err.message || "An unknown error occurred");
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return <div className="text-[var(--slate)] animate-pulse">Loading system configuration...</div>;
  }

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div>
        <h2 className="text-2xl font-serif text-[var(--foreground)] mb-2">Account Settings</h2>
        <p className="text-sm text-[var(--slate)]">
          Manage your system integrations and API keys. These keys are stored securely on your local server.
        </p>
      </div>

      <div className="space-y-6">
        <div className="bg-[var(--background)] border border-[var(--border-color)] rounded-lg p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-full bg-blue-500/10 flex items-center justify-center text-blue-400">
              <Key className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-lg font-medium text-[var(--foreground)]">Gemini API Key</h3>
              <p className="text-xs text-[var(--slate)]">Required for AI-powered screener, technicals, and newsletter generation.</p>
            </div>
          </div>

          <div className="space-y-4">
            <div className="flex flex-col gap-2">
              <label className="text-sm font-medium text-[var(--slate)]">API Key</label>
              <div className="flex gap-4">
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="AIzaSy..."
                  className="flex-1 bg-[var(--card-bg)] border border-[var(--border-color)] rounded-md px-4 py-2 text-sm text-[var(--foreground)] focus:outline-none focus:border-brand-gold transition-colors font-mono"
                />
                <button
                  onClick={handleSave}
                  disabled={isSaving}
                  className="bg-brand-gold hover:bg-brand-gold-light text-black px-6 py-2 rounded-md text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                  {isSaving ? "Saving..." : (
                    <>
                      <Save className="w-4 h-4" /> Save
                    </>
                  )}
                </button>
              </div>
            </div>

            {status === "success" && (
              <div className="flex items-center gap-2 text-green-500 text-sm bg-green-500/10 p-3 rounded-md border border-green-500/20">
                <CheckCircle2 className="w-4 h-4" />
                API key updated successfully in secrets.toml
              </div>
            )}

            {status === "error" && (
              <div className="flex items-center gap-2 text-red-500 text-sm bg-red-500/10 p-3 rounded-md border border-red-500/20">
                <AlertCircle className="w-4 h-4" />
                {errorMessage}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
