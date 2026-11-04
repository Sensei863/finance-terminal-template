import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, CrosshairMode, AreaSeries } from 'lightweight-charts';

export function RiskMetricsChart({ data }: { data: any[] }) {
  const volContainerRef = useRef<HTMLDivElement>(null);
  const ddContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!data || data.length === 0 || !volContainerRef.current || !ddContainerRef.current) return;

    // --- Volatility Chart ---
    const volChart = createChart(volContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#64748b' },
      grid: { vertLines: { color: '#334155', style: 1 }, horzLines: { color: '#334155', style: 1 } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', visible: false },
    });

    const volSeries = volChart.addSeries(AreaSeries, {
      lineColor: '#f59e0b',
      topColor: 'rgba(245, 158, 11, 0.4)',
      bottomColor: 'rgba(245, 158, 11, 0.0)',
      lineWidth: 2,
    });
    volSeries.setData(data.filter(d => d.volatility !== null).map(d => ({ time: d.time, value: d.volatility })));

    // --- Drawdown Chart ---
    const ddChart = createChart(ddContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#64748b' },
      grid: { vertLines: { color: '#334155', style: 1 }, horzLines: { color: '#334155', style: 1 } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155' },
    });

    const ddSeries = ddChart.addSeries(AreaSeries, {
      lineColor: '#ef4444',
      topColor: 'rgba(239, 68, 68, 0.4)',
      bottomColor: 'rgba(239, 68, 68, 0.0)',
      lineWidth: 2,
    });
    ddSeries.setData(data.filter(d => d.drawdown !== null).map(d => ({ time: d.time, value: d.drawdown })));

    const charts = [volChart, ddChart];
    
    volChart.timeScale().fitContent();

    charts.forEach((chart, idx) => {
      chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (!range) return;
        charts.forEach((c, i) => {
          if (i !== idx) c.timeScale().setVisibleLogicalRange(range);
        });
      });

      chart.subscribeCrosshairMove(param => {
        const time = param.time;
        if (!time) {
          charts.forEach(c => c.clearCrosshairPosition());
          return;
        }
      });
    });

    const handleResize = () => {
      volChart.applyOptions({ width: volContainerRef.current?.clientWidth });
      ddChart.applyOptions({ width: ddContainerRef.current?.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      volChart.remove();
      ddChart.remove();
    };
  }, [data]);

  return (
    <div className="flex flex-col w-full border border-[var(--border-color)] rounded-xl overflow-hidden bg-[var(--background)]">
      <div className="relative w-full h-[200px]">
        <div className="absolute top-2 left-4 z-10 text-xs font-semibold text-brand-slate uppercase tracking-wider">
          30-Day Rolling Annualised Volatility (%)
        </div>
        <div ref={volContainerRef} className="w-full h-full" />
      </div>
      <div className="w-full h-[1px] bg-[var(--border-color)]" />
      <div className="relative w-full h-[200px]">
        <div className="absolute top-2 left-4 z-10 text-xs font-semibold text-brand-slate uppercase tracking-wider">
          Drawdown from Peak (%)
        </div>
        <div ref={ddContainerRef} className="w-full h-full" />
      </div>
    </div>
  );
}
