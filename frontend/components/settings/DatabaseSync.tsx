"use client";

import React, { useState, useEffect } from "react";
import { Database, RefreshCw, ArrowUpCircle, ArrowDownCircle } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function DatabaseSync() {
  const [dbStatus, setDbStatus] = useState<any>(null);
  const [isSyncing, setIsSyncing] = useState<string | null>(null);
  const [dbStatusLoading, setDbStatusLoading] = useState(false);

  const fetchDbStatus = async () => {
    setDbStatusLoading(true);
    try {
      const res = await fetch(`${API}/api/system/db-status`);
      if (res.ok) {
        const d = await res.json();
        setDbStatus(d);
      }
    } catch (e) {
      console.error("Failed to load database status", e);
    } finally {
      setDbStatusLoading(false);
    }
  };

  const handleDbSync = async (direction: "push" | "pull") => {
    setIsSyncing(direction);
    try {
      const res = await fetch(`${API}/api/system/db-sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ direction })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Sync failed");
      }
      alert(`Database sync (${direction === "push" ? "Local to Cloud" : "Cloud to Local"}) completed successfully!`);
      fetchDbStatus();
    } catch (e: any) {
      alert(`Sync Error: ${e.message}`);
    } finally {
      setIsSyncing(null);
    }
  };

  useEffect(() => {
    fetchDbStatus();
  }, []);

  return (
    <section className="space-y-4 pb-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <h3 className="text-lg font-medium text-[var(--foreground)] border-l-2 border-brand-gold pl-3 flex items-center gap-2">
        <Database className="w-5 h-5 text-brand-gold" /> Database Connection &amp; Sync Status
      </h3>
      <p className="text-xs text-[var(--slate)]">
        Monitor database states between local SQLite files and the cloud Supabase instance. Clear and copy tables bi-directionally.
      </p>

      {dbStatusLoading && !dbStatus ? (
        <div className="text-xs text-[var(--slate)] animate-pulse">Fetching connection info...</div>
      ) : dbStatus ? (
        <div className="space-y-4 max-w-2xl bg-[var(--background)] border border-[var(--border-color)] p-6 rounded-lg shadow-sm">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 text-sm">
            <div>
              <div className="text-[var(--slate)] uppercase text-[10px] tracking-wider font-semibold mb-1">Instance Database</div>
              <div className="font-semibold text-brand-gold">{dbStatus.db_type}</div>
            </div>
            <div>
              <div className="text-[var(--slate)] uppercase text-[10px] tracking-wider font-semibold mb-1">Sync Capabilities</div>
              <div className={dbStatus.is_sync_capable ? "text-green-500 font-semibold" : "text-red-500 font-semibold"}>
                {dbStatus.is_sync_capable ? "Enabled" : "Disabled (Offline)"}
              </div>
            </div>
            <div>
              <div className="text-[var(--slate)] uppercase text-[10px] tracking-wider font-semibold mb-1">Local SQLite Data</div>
              <div className="font-mono text-[var(--foreground)]">
                {dbStatus.local_rows} rows 
                <div className="text-xs text-[var(--slate)] mt-0.5">
                  {dbStatus.local_last_write ? `Last: ${new Date(dbStatus.local_last_write).toLocaleDateString()}` : "No runs"}
                </div>
              </div>
            </div>
            <div>
              <div className="text-[var(--slate)] uppercase text-[10px] tracking-wider font-semibold mb-1">Cloud PG Data</div>
              <div className="font-mono text-[var(--foreground)]">
                {dbStatus.cloud_rows} rows
                <div className="text-xs text-[var(--slate)] mt-0.5">
                  {dbStatus.cloud_last_write ? `Last: ${new Date(dbStatus.cloud_last_write).toLocaleDateString()}` : "No runs"}
                </div>
              </div>
            </div>
          </div>

          {dbStatus.is_sync_capable && (
            <div className="text-sm border-t border-[var(--border-color)] pt-4 mt-4 text-[var(--slate)]">
              {dbStatus.local_rows !== dbStatus.cloud_rows ? (
                <div className="text-brand-gold font-semibold mb-2">
                  ⚠️ Data mismatch detected! Local has {dbStatus.local_rows} rows, Cloud has {dbStatus.cloud_rows} rows.
                </div>
              ) : (
                <div className="text-green-500 font-semibold mb-2 flex items-center gap-1.5">
                  ✓ Database row counts match! ({dbStatus.local_rows} rows)
                </div>
              )}
              
              {dbStatus.local_last_write && dbStatus.cloud_last_write && (
                <div className="mt-2 text-xs">
                  {new Date(dbStatus.local_last_write) > new Date(dbStatus.cloud_last_write) ? (
                    <span className="text-brand-gold bg-brand-gold/10 px-2 py-1 rounded">Local database has newer writes. Cloud database is behind.</span>
                  ) : new Date(dbStatus.cloud_last_write) > new Date(dbStatus.local_last_write) ? (
                    <span className="text-brand-gold bg-brand-gold/10 px-2 py-1 rounded">Cloud database has newer writes. Local database is behind.</span>
                  ) : (
                    <span className="text-[var(--slate)]">Databases are perfectly in sync based on last write timestamp.</span>
                  )}
                </div>
              )}

              <div className="flex flex-col gap-1 mt-4 text-xs text-[var(--slate)] font-mono bg-[var(--card-bg)] p-3 rounded border border-[var(--border-color)]/50">
                {dbStatus.last_push_sync && <div>Last Push (Local ➜ Cloud): {new Date(dbStatus.last_push_sync).toLocaleString()}</div>}
                {dbStatus.last_pull_sync && <div>Last Pull (Cloud ➜ Local): {new Date(dbStatus.last_pull_sync).toLocaleString()}</div>}
                {!dbStatus.last_push_sync && !dbStatus.last_pull_sync && <div>No recent manual sync recorded.</div>}
              </div>
            </div>
          )}

          {dbStatus.is_sync_capable && (dbStatus.is_prod || process.env.NODE_ENV === 'production') ? (
            <div className="border-t border-[var(--border-color)] pt-6 mt-4 text-center">
               <span className="text-brand-gold bg-brand-gold/10 px-4 py-2 rounded text-sm font-semibold inline-flex items-center gap-2">
                 ⚠️ Manual sync is disabled in production environments.
               </span>
            </div>
          ) : dbStatus.is_sync_capable && (
            <div className="flex flex-col sm:flex-row gap-4 border-t border-[var(--border-color)] pt-6 mt-4">
              <button
                onClick={() => handleDbSync("push")}
                disabled={isSyncing !== null}
                className="flex-1 flex items-center justify-center gap-2 bg-brand-gold text-[var(--background)] hover:bg-[#b58b38] px-4 py-2.5 rounded text-xs font-bold tracking-wider uppercase transition-colors disabled:opacity-50"
              >
                {isSyncing === "push" ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <ArrowUpCircle className="w-4 h-4" />
                )}
                Push Local to Cloud
              </button>
              
              <button
                onClick={() => handleDbSync("pull")}
                disabled={isSyncing !== null}
                className="flex-1 flex items-center justify-center gap-2 border-2 border-brand-gold text-brand-gold hover:bg-brand-gold/10 px-4 py-2.5 rounded text-xs font-bold tracking-wider uppercase transition-colors disabled:opacity-50"
              >
                {isSyncing === "pull" ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <ArrowDownCircle className="w-4 h-4" />
                )}
                Pull Cloud to Local
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="text-xs text-[var(--slate)]">Could not fetch database information.</div>
      )}
    </section>
  );
}
