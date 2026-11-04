"use client";

import React, { useState } from "react";
import { Settings, BarChart2, Activity, Moon, Database, Sliders, Bell, TrendingUp } from "lucide-react";
import { BenchmarkBuilder } from "@/components/settings/BenchmarkBuilder";
import { AccountSettings } from "@/components/settings/AccountSettings";
import { PromptEditor } from "@/components/settings/PromptEditor";
import { Diagnostics } from "@/components/settings/Diagnostics";
import { NightlyRunLog } from "@/components/settings/NightlyRunLog";
import { DatabaseSync } from "@/components/settings/DatabaseSync";

import { DowntrendAlerts } from "@/components/settings/DowntrendAlerts";
import { UptrendAlerts } from "@/components/settings/UptrendAlerts";

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState("account");

  return (
    <div className="min-h-screen bg-[var(--background)]">
      {/* Hero Section */}
      <div className="relative h-64 overflow-hidden">
        {/* Background Image */}
        <div 
          className="absolute inset-0 bg-center bg-no-repeat"
          style={{ backgroundImage: 'url("/settings-hero.png")', backgroundSize: '85% auto', backgroundPosition: 'center 25%' }}
        />
        {/* Thematic overlay with subtle gradient */}
        <div className="absolute inset-0 bg-gradient-to-b from-[var(--background)]/70 via-[var(--background)]/30 to-[var(--background)]" />
        
        {/* Top Gold Bar */}
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-brand-gold to-[#e8c37d]" />

        <div className="relative h-full flex flex-col justify-end pb-8 px-8 max-w-7xl mx-auto w-full">
          <div className="flex items-center gap-3 mb-2">
            <span className="h-px w-8 bg-brand-gold" />
            <span className="text-[10px] uppercase tracking-widest text-brand-gold font-bold">System Configuration</span>
          </div>
          <h1 className="text-4xl md:text-5xl font-serif text-[var(--foreground)] tracking-tight">
            Settings <span className="text-brand-slate italic font-light">& Preferences</span>
          </h1>
        </div>
      </div>

      {/* CONTENT & NAVIGATION */}
      <div className="max-w-7xl mx-auto w-full px-8 py-12 flex flex-col md:flex-row gap-12">
        
        {/* SIDEBAR NAVIGATION */}
        <aside className="w-full md:w-64 flex-shrink-0">
          <div className="flex flex-col gap-2">
            <button
              onClick={() => setActiveTab("account")}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                activeTab === "account" 
                  ? "bg-[var(--card-bg)] text-brand-gold border border-[var(--border-color)] shadow-sm"
                  : "text-[var(--slate)] hover:text-[var(--foreground)] hover:bg-[var(--card-bg)] border border-transparent"
              }`}
            >
              <Settings className="w-4 h-4" />
              Account Settings
            </button>
            <button
              onClick={() => setActiveTab("prompts")}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                activeTab === "prompts" 
                  ? "bg-[var(--card-bg)] text-brand-gold border border-[var(--border-color)] shadow-sm"
                  : "text-[var(--slate)] hover:text-[var(--foreground)] hover:bg-[var(--card-bg)] border border-transparent"
              }`}
            >
              <Sliders className="w-4 h-4" />
              Prompt Templates
            </button>
            <button
              onClick={() => setActiveTab("benchmark")}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                activeTab === "benchmark" 
                  ? "bg-[var(--card-bg)] text-brand-gold border border-[var(--border-color)] shadow-sm"
                  : "text-[var(--slate)] hover:text-[var(--foreground)] hover:bg-[var(--card-bg)] border border-transparent"
              }`}
            >
              <BarChart2 className="w-4 h-4" />
              Benchmark Builder
            </button>
            <button
              onClick={() => setActiveTab("alerts")}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                activeTab === "alerts" 
                  ? "bg-[var(--card-bg)] text-brand-gold border border-[var(--border-color)] shadow-sm"
                  : "text-[var(--slate)] hover:text-[var(--foreground)] hover:bg-[var(--card-bg)] border border-transparent"
              }`}
            >
              <Bell className="w-4 h-4" />
              Downtrend Alerts
            </button>
            <button
              onClick={() => setActiveTab("uptrend-alerts")}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                activeTab === "uptrend-alerts" 
                  ? "bg-[var(--card-bg)] text-emerald-400 border border-[var(--border-color)] shadow-sm"
                  : "text-[var(--slate)] hover:text-[var(--foreground)] hover:bg-[var(--card-bg)] border border-transparent"
              }`}
            >
              <TrendingUp className="w-4 h-4 text-emerald-400" />
              Uptrend Alerts
            </button>
            <button
              onClick={() => setActiveTab("nightly")}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                activeTab === "nightly" 
                  ? "bg-[var(--card-bg)] text-brand-gold border border-[var(--border-color)] shadow-sm"
                  : "text-[var(--slate)] hover:text-[var(--foreground)] hover:bg-[var(--card-bg)] border border-transparent"
              }`}
            >
              <Moon className="w-4 h-4" />
              Nightly Run Log
            </button>
            <button
              onClick={() => setActiveTab("db-sync")}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                activeTab === "db-sync" 
                  ? "bg-[var(--card-bg)] text-brand-gold border border-[var(--border-color)] shadow-sm"
                  : "text-[var(--slate)] hover:text-[var(--foreground)] hover:bg-[var(--card-bg)] border border-transparent"
              }`}
            >
              <Database className="w-4 h-4" />
              Database & Sync
            </button>
            <button
              onClick={() => setActiveTab("diagnostics")}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                activeTab === "diagnostics" 
                  ? "bg-[var(--card-bg)] text-brand-gold border border-[var(--border-color)] shadow-sm"
                  : "text-[var(--slate)] hover:text-[var(--foreground)] hover:bg-[var(--card-bg)] border border-transparent"
              }`}
            >
              <Activity className="w-4 h-4" />
              Diagnostics & Tools
            </button>
          </div>
        </aside>

        {/* MAIN PANEL */}
        <main className="flex-1">
          <div className="bg-[var(--card-bg)] border border-[var(--border-color)] rounded-xl p-8 shadow-sm">
            {activeTab === "account" && <AccountSettings />}
            {activeTab === "prompts" && <PromptEditor />}
            {activeTab === "benchmark" && <BenchmarkBuilder />}
            {activeTab === "alerts" && <DowntrendAlerts />}
            {activeTab === "uptrend-alerts" && <UptrendAlerts />}
            {activeTab === "nightly" && <NightlyRunLog />}
            {activeTab === "db-sync" && <DatabaseSync />}
            {activeTab === "diagnostics" && <Diagnostics />}
          </div>
        </main>

      </div>
    </div>
  );
}
