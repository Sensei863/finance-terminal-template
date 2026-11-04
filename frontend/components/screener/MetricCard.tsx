import React from "react";
import { Info } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string;
  explanation: string;
  valueColor?: string;
  subValue?: React.ReactNode;
}

export function MetricCard({ label, value, explanation, valueColor, subValue }: MetricCardProps) {
  return (
    <div className="bg-[var(--background)] p-4 rounded-lg border border-[var(--border-color)] shadow-sm relative group transition-all hover:border-brand-gold hover:shadow-md hover:-translate-y-1 duration-300 ease-in-out">
      <div className="text-sm text-brand-navy/60 dark:text-gray-400 font-medium tracking-wide">
        {label}
      </div>
      <div className={`text-2xl font-bold mt-1 ${valueColor || "text-brand-navy dark:text-white"}`}>
        {value}
      </div>
      {subValue && (
        <div className="text-xs text-brand-navy/50 dark:text-gray-500 mt-2">
          {subValue}
        </div>
      )}
      
      {/* Explanation Tooltip / Reveal */}
      <details className="mt-3 group-open:bg-gray-50 dark:group-open:bg-white/5 p-2 rounded-md transition-colors">
        <summary className="text-xs cursor-pointer text-brand-gold flex items-center gap-1 font-medium select-none">
          <Info className="w-3 h-3" /> Explanation
        </summary>
        <div className="text-xs text-brand-navy/70 dark:text-gray-300 mt-2 leading-relaxed">
          {explanation}
        </div>
      </details>
    </div>
  );
}
