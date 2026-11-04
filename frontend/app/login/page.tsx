"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { Lock } from "lucide-react";

export default function LoginPage() {
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState(false);
  const router = useRouter();

  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    
    try {
      const res = await fetch("/api/auth/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passcode }),
      });

      if (res.ok) {
        // Also keep legacy auth_passcode cookie for backward compatibility with existing components
        document.cookie = `auth_passcode=${encodeURIComponent(passcode)}; path=/; max-age=${60 * 60 * 24 * 30}`;
        router.push("/");
      } else {
        setError(true);
        setPasscode("");
      }
    } catch {
      setError(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--background)]">
      <div className="max-w-md w-full p-8 border border-[var(--border-color)] bg-white shadow-sm flex flex-col items-center">
        <div className="w-12 h-12 rounded-full bg-brand-gold/10 flex items-center justify-center mb-6">
          <Lock className="w-6 h-6 text-brand-gold" />
        </div>
        
        <h1 className="text-3xl font-serif text-brand-gold mb-2 tracking-tight text-center">
          Aegis Terminal
        </h1>
        <p className="text-sm text-brand-slate mb-8 text-center">
          Please enter your secure passcode to access your portfolio and analytics.
        </p>

        <form onSubmit={handleSubmit} className="w-full space-y-6">
          <div>
            <input
              type="password"
              placeholder="Enter Passcode"
              value={passcode}
              onChange={(e) => {
                setPasscode(e.target.value);
                setError(false);
              }}
              className={`w-full px-4 py-3 text-center tracking-[0.3em] text-lg outline-none border focus:border-brand-gold transition-colors ${
                error ? "border-red-500 bg-red-50" : "border-[var(--border-color)] bg-[var(--background)]"
              }`}
              autoFocus
            />
            {error && (
              <p className="text-red-500 text-xs mt-2 text-center uppercase tracking-wider font-semibold">
                Incorrect Passcode
              </p>
            )}
          </div>

          <button
            type="submit"
            className="w-full bg-brand-navy hover:bg-brand-navy-light text-white transition-colors py-3 uppercase text-xs tracking-wider font-bold"
          >
            Unlock Terminal
          </button>
        </form>
      </div>
    </div>
  );
}
