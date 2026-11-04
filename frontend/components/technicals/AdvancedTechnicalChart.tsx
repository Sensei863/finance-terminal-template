import React, { useEffect, useRef } from 'react';
import { createChart, ColorType, CrosshairMode, CandlestickSeries, LineSeries, HistogramSeries } from 'lightweight-charts';

export function AdvancedTechnicalChart({ data }: { data: any[] }) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!data || data.length === 0 || !chartContainerRef.current || !rsiContainerRef.current || !macdContainerRef.current) return;

    // --- Main Chart (Price, SMA, BB, Volume) ---
    const mainChart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#64748b' },
      grid: { vertLines: { color: '#334155', style: 1 }, horzLines: { color: '#334155', style: 1 } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', visible: false }, // Hide time axis on main
    });

    const candlestickSeries = mainChart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#10b981', wickDownColor: '#ef4444',
    });
    candlestickSeries.setData(data.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close })));

    const sma50Series = mainChart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2 });
    sma50Series.setData(data.filter(d => d.sma50 !== null).map(d => ({ time: d.time, value: d.sma50 })));

    const sma200Series = mainChart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2 });
    sma200Series.setData(data.filter(d => d.sma200 !== null).map(d => ({ time: d.time, value: d.sma200 })));

    // Bollinger Bands (20-day, ±2σ) — two dashed lines
    const bbUpperSeries = mainChart.addSeries(LineSeries, {
      color: 'rgba(6, 182, 212, 0.85)',
      lineWidth: 2,
      lineStyle: 2, // dashed
      title: '',
      lastValueVisible: false,
      priceLineVisible: false,
    });
    bbUpperSeries.setData(
      data.filter(d => d.bb_upper !== null).map(d => ({ time: d.time, value: d.bb_upper }))
    );

    const bbLowerSeries = mainChart.addSeries(LineSeries, {
      color: 'rgba(6, 182, 212, 0.85)',
      lineWidth: 2,
      lineStyle: 2, // dashed
      title: '',
      lastValueVisible: false,
      priceLineVisible: false,
    });
    bbLowerSeries.setData(
      data.filter(d => d.bb_lower !== null).map(d => ({ time: d.time, value: d.bb_lower }))
    );

    const volumeSeries = mainChart.addSeries(HistogramSeries, {
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: '', // set as an overlay
      scaleMargins: { top: 0.8, bottom: 0 },
    } as any);
    volumeSeries.setData(data.map(d => ({ 
      time: d.time, 
      value: d.value, 
      color: d.close > d.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)' 
    })));

    // --- RSI Chart ---
    const rsiChart = createChart(rsiContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#64748b' },
      grid: { vertLines: { color: '#334155', style: 1 }, horzLines: { color: '#334155', style: 1 } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', visible: false },
    });

    const rsiSeries = rsiChart.addSeries(LineSeries, { color: '#d946ef', lineWidth: 2 });
    rsiSeries.setData(data.filter(d => d.rsi !== null).map(d => ({ time: d.time, value: d.rsi })));

    // Add 30/70 reference lines manually
    const rsiHigh = rsiChart.addSeries(LineSeries, { color: 'rgba(239, 68, 68, 0.5)', lineWidth: 1, lineStyle: 2 });
    rsiHigh.setData(data.map(d => ({ time: d.time, value: 70 })));
    const rsiLow = rsiChart.addSeries(LineSeries, { color: 'rgba(16, 185, 129, 0.5)', lineWidth: 1, lineStyle: 2 });
    rsiLow.setData(data.map(d => ({ time: d.time, value: 30 })));

    // --- MACD Chart ---
    const macdChart = createChart(macdContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#64748b' },
      grid: { vertLines: { color: '#334155', style: 1 }, horzLines: { color: '#334155', style: 1 } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155' }, // Show time axis on bottom chart
    });

    const macdLine = macdChart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2 });
    macdLine.setData(data.filter(d => d.macd !== null).map(d => ({ time: d.time, value: d.macd })));

    const signalLine = macdChart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2 });
    signalLine.setData(data.filter(d => d.macd_signal !== null).map(d => ({ time: d.time, value: d.macd_signal })));

    const macdHist = macdChart.addSeries(HistogramSeries, {
      color: '#10b981',
    });
    macdHist.setData(data.filter(d => d.macd_hist !== null).map(d => ({ 
      time: d.time, 
      value: d.macd_hist,
      color: d.macd_hist > 0 ? 'rgba(16, 185, 129, 0.8)' : 'rgba(239, 68, 68, 0.8)'
    })));

    // Sync Crosshairs & Visible Range
    const charts = [mainChart, rsiChart, macdChart];
    
    // Auto-fit data
    mainChart.timeScale().fitContent();

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
        charts.forEach((c, i) => {
          if (i !== idx) {
            // we can't perfectly set price crosshair sync unless we know the price matching that time,
            // but we can at least sync the vertical line!
            const series = i === 0 ? candlestickSeries : i === 1 ? rsiSeries : macdLine;
            const dataPt = param.seriesData.get(series);
            const price = dataPt ? (dataPt as any).value || (dataPt as any).close : 0;
            // Note: crosshair syncing for price is hacky in lightweight-charts without pro,
            // we will just rely on the timescale sync which handles the vertical line alignment well enough implicitly.
          }
        });
      });
    });

    const handleResize = () => {
      mainChart.applyOptions({ width: chartContainerRef.current?.clientWidth });
      rsiChart.applyOptions({ width: rsiContainerRef.current?.clientWidth });
      macdChart.applyOptions({ width: macdContainerRef.current?.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      mainChart.remove();
      rsiChart.remove();
      macdChart.remove();
    };
  }, [data]);

  return (
    <div className="flex flex-col w-full border border-[var(--border-color)] rounded-xl overflow-hidden bg-[var(--background)]">
      <div className="relative w-full h-[400px]">
        <div className="absolute top-2 left-4 z-10 text-xs font-semibold text-brand-slate uppercase tracking-wider">
          Price, SMA 50 (Blue), SMA 200 (Gold), BB (Dashed), Volume
        </div>
        <div ref={chartContainerRef} className="w-full h-full" />
      </div>
      <div className="w-full h-[1px] bg-[var(--border-color)]" />
      <div className="relative w-full h-[150px]">
        <div className="absolute top-2 left-4 z-10 text-xs font-semibold text-brand-slate uppercase tracking-wider">
          RSI (14)
        </div>
        <div ref={rsiContainerRef} className="w-full h-full" />
      </div>
      <div className="w-full h-[1px] bg-[var(--border-color)]" />
      <div className="relative w-full h-[200px]">
        <div className="absolute top-2 left-4 z-10 text-xs font-semibold text-brand-slate uppercase tracking-wider">
          MACD (12, 26, 9)
        </div>
        <div ref={macdContainerRef} className="w-full h-full" />
      </div>
    </div>
  );
}
