'use client';

import { useEffect, useMemo, useState } from 'react';
import { Activity, Gauge, Radio, ScanSearch } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { OptionSurface3D } from '@/components/option-surface-3d';

export type FeatureRow = {
  timestamp: string; target_dte: number; actual_dte: number; expiration_date: string;
  symbol: string; option_type: 'call' | 'put'; strike: number; session_minute: number;
  option_close: number; option_momentum_5m: number | null; option_momentum_15m: number | null;
  underlying_price: number; spy_momentum_5m: number | null; spy_momentum_15m: number | null;
  spy_momentum_30m: number | null; spy_from_open_pct: number | null; spy_vwap: number | null;
  spy_vwap_distance_pct: number | null; spy_intraday_high: number; spy_intraday_low: number;
  spy_high_distance_pct: number; spy_low_distance_pct: number; implied_volatility: number | null;
  iv_change_5m: number | null; iv_change_15m: number | null; moneyness_pct: number;
  volume: number; trade_count: number; catalyst_types: string[]; catalyst_age_minutes: number | null;
  quote_at: string | null; bid: number | null; bid_size: number | null; ask: number | null;
  ask_size: number | null; mid: number | null; spread: number | null; spread_pct: number | null;
  quote_age_seconds: number | null; quote_source: string | null;
};
type FeatureData = { market_date: string; rows: FeatureRow[]; quoted_rows: number;
  latest_quote_capture: string | null; quote_status: string };

const percent = (value: number | null, digits = 2) => value == null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
const timeLabel = (timestamp: string) => new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }).format(new Date(timestamp));

export function SignalLab({ marketDate }: { marketDate: string }) {
  const [data, setData] = useState<FeatureData | null>(null);
  const [dte, setDte] = useState(0);
  const [surfaceType, setSurfaceType] = useState<'call' | 'put'>('call');
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [selectedTimestamp, setSelectedTimestamp] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/features/${marketDate}`).then((response) => response.json()).then((result) => {
      setData(result); setSelectedSymbol(null); setSelectedTimestamp(null);
    }).catch(() => setData({ market_date: marketDate, rows: [], quoted_rows: 0, latest_quote_capture: null, quote_status: 'error' }));
  }, [marketDate]);

  const surfaceRows = useMemo(() => (data?.rows ?? []).filter((row) => row.target_dte === dte), [data, dte]);
  const timestamps = useMemo(() => [...new Set(surfaceRows.map((row) => row.timestamp))].sort(), [surfaceRows]);
  const selectedTime = selectedTimestamp ?? timestamps.at(-1);
  const atTime = useMemo(() => (data?.rows ?? []).filter((row) => row.timestamp === selectedTime && row.target_dte === dte), [data, selectedTime, dte]);
  const selected = atTime.find((row) => row.symbol === selectedSymbol) ?? atTime.find((row) => row.option_type === surfaceType && row.implied_volatility != null) ?? atTime[0];
  const market = selected ?? (data?.rows ?? []).find((row) => row.timestamp === selectedTime);
  const catalysts = [...new Set((data?.rows ?? []).filter((row) => row.timestamp === selectedTime).flatMap((row) => row.catalyst_types))];
  const surfaceIv = atTime.filter((row) => row.implied_volatility != null).map((row) => row.implied_volatility!);
  const ivChange = atTime.filter((row) => row.iv_change_15m != null).map((row) => row.iv_change_15m!);
  const average = (values: number[]) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  const volume = atTime.reduce((sum, row) => sum + (row.volume || 0), 0);

  if (!data) return <section className="grid min-h-64 place-items-center border border-white/8 bg-[#081410] font-mono text-xs text-slate-500">Building Signal Lab…</section>;
  if (!data.rows.length) return <section className="border border-white/8 bg-[#081410] p-5"><p className="font-mono text-xs text-slate-400">Signal Lab features are not materialized for this session.</p></section>;

  return <section className="overflow-hidden border border-cyan-300/15 bg-[#071513]">
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/8 px-4 py-3 md:px-5">
      <div><p className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-200/70"><ScanSearch className="size-3.5" />Signal Lab</p><h2 className="mt-1 text-xl font-semibold">Market state × option surface</h2></div>
      <div className={`flex items-center gap-2 border px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-wider ${data.quoted_rows ? 'border-emerald-300/25 text-emerald-200' : 'border-amber-200/20 text-amber-100/60'}`}><Radio className="size-3" />{data.quoted_rows ? `${data.quoted_rows} quoted rows` : 'Trade bars only · quotes start forward'}</div>
    </div>

    <div className="grid gap-0 xl:grid-cols-[minmax(0,1fr)_330px]">
      <div className="min-w-0 p-4 md:p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-3"><div className="flex gap-1">{[0, 30, 60, 120].map((value) => <Button key={value} size="sm" variant={dte === value ? 'default' : 'outline'} onClick={() => { setDte(value); setSelectedSymbol(null); setSelectedTimestamp(null); }} className="font-mono text-[10px]">{value}D</Button>)}</div><div className="flex gap-1">{(['call', 'put'] as const).map((value) => <Button key={value} size="sm" variant={surfaceType === value ? 'default' : 'outline'} onClick={() => { setSurfaceType(value); setSelectedSymbol(null); setSelectedTimestamp(null); }} className="font-mono text-[10px] uppercase">{value}s</Button>)}</div></div>
          <p className="font-mono text-sm font-semibold text-cyan-100">{selectedTime ? timeLabel(selectedTime) : '—'} <span className="text-[10px] font-normal text-slate-600">selected ET</span></p>
        </div>

        <div className="grid grid-cols-2 gap-px bg-white/8 sm:grid-cols-3 lg:grid-cols-6">
          <Metric label="SPY 15m" value={percent(market?.spy_momentum_15m ?? null)} tone={(market?.spy_momentum_15m ?? 0) >= 0} />
          <Metric label="From open" value={percent(market?.spy_from_open_pct ?? null)} tone={(market?.spy_from_open_pct ?? 0) >= 0} />
          <Metric label="vs VWAP" value={percent(market?.spy_vwap_distance_pct ?? null)} tone={(market?.spy_vwap_distance_pct ?? 0) >= 0} />
          <Metric label="Surface IV" value={average(surfaceIv) == null ? '—' : `${(average(surfaceIv)! * 100).toFixed(1)}%`} />
          <Metric label="ΔIV 15m" value={average(ivChange) == null ? '—' : `${(average(ivChange)! * 100).toFixed(2)} vol`} tone={(average(ivChange) ?? 0) >= 0} />
          <Metric label="Option volume" value={volume.toLocaleString()} />
        </div>

        <div className="mt-5"><div className="mb-2 flex items-center justify-between gap-4"><p className="font-mono text-[9px] uppercase tracking-[0.18em] text-slate-500">Session IV surface · time × strike × implied volatility</p><p className="font-mono text-[8px] text-slate-600">{surfaceType === 'call' ? 'emerald calls' : 'amber puts'} · clipped to 5th–95th IV percentile</p></div>
          <OptionSurface3D rows={surfaceRows} optionType={surfaceType} selectedSymbol={selectedSymbol} selectedTimestamp={selectedTime ?? null} onSelect={(row) => { setSelectedSymbol(row.symbol); setSelectedTimestamp(row.timestamp); }} />
        </div>
      </div>

      <aside className="border-t border-white/8 bg-[#091a17] p-4 xl:border-l xl:border-t-0">
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500">Selected contract</p>
        {selected ? <><div className="mt-2 flex items-start justify-between"><div><h3 className="font-mono text-sm font-semibold text-slate-100">{selected.option_type === 'call' ? 'CALL' : 'PUT'} {selected.strike.toFixed(0)}</h3><p className="mt-1 truncate font-mono text-[8px] text-slate-600" title={selected.symbol}>{selected.symbol}</p></div><p className="font-mono text-sm text-slate-200">${selected.option_close.toFixed(2)}</p></div>
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 font-mono"><Fact label="DTE" value={`${selected.actual_dte}d`} /><Fact label="Moneyness" value={percent(selected.moneyness_pct)} /><Fact label="Momentum 5m" value={percent(selected.option_momentum_5m)} /><Fact label="Momentum 15m" value={percent(selected.option_momentum_15m)} /><Fact label="IV" value={selected.implied_volatility == null ? '—' : `${(selected.implied_volatility * 100).toFixed(1)}%`} /><Fact label="ΔIV 15m" value={selected.iv_change_15m == null ? '—' : `${(selected.iv_change_15m * 100).toFixed(2)} vol`} /><Fact label="Volume" value={selected.volume?.toLocaleString() ?? '—'} /><Fact label="Trades" value={selected.trade_count?.toLocaleString() ?? '—'} /></dl>
          <div className="mt-5 border-t border-white/8 pt-4"><p className="mb-3 flex items-center gap-2 font-mono text-[9px] uppercase tracking-wider text-slate-500"><Gauge className="size-3" />Executable quote</p>{selected.bid != null && selected.ask != null ? <div className="grid grid-cols-3 gap-2 text-center font-mono"><Quote label="Bid" value={selected.bid} /><Quote label="Mid" value={selected.mid} /><Quote label="Ask" value={selected.ask} /><p className="col-span-3 mt-1 text-[9px] text-slate-500">Spread {selected.spread_pct?.toFixed(2)}% · {selected.quote_source}</p></div> : <div className="border border-amber-200/15 bg-amber-200/[.035] p-3 text-xs leading-relaxed text-amber-100/60">No historical bid/ask was supplied by Alpaca for this bar. Forward minute snapshots will populate this rail without inventing prices.</div>}</div>
        </> : <p className="mt-3 text-sm text-slate-500">No traded contracts at this timestamp and DTE.</p>}
        <div className="mt-5 border-t border-white/8 pt-4"><p className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-wider text-slate-500"><Activity className="size-3" />Catalyst context</p><div className="mt-3 flex flex-wrap gap-1.5">{catalysts.length ? catalysts.map((item) => <span key={item} className="border border-cyan-200/15 bg-cyan-200/[.04] px-2 py-1 font-mono text-[9px] uppercase text-cyan-100/70">{item}</span>) : <span className="font-mono text-[9px] text-slate-600">No matched catalyst in prior 60m</span>}</div></div>
      </aside>
    </div>
  </section>;
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: boolean }) { return <div className="bg-[#0a1b17] p-3"><p className="font-mono text-[8px] uppercase tracking-wider text-slate-600">{label}</p><p className={`mt-1 font-mono text-sm font-semibold ${tone == null ? 'text-slate-200' : tone ? 'text-emerald-300' : 'text-rose-300'}`}>{value}</p></div>; }
function Fact({ label, value }: { label: string; value: string }) { return <div><dt className="text-[8px] uppercase tracking-wider text-slate-600">{label}</dt><dd className="mt-1 text-[11px] text-slate-300">{value}</dd></div>; }
function Quote({ label, value }: { label: string; value: number | null }) { return <div className="border border-white/8 bg-black/10 p-2"><p className="text-[8px] uppercase text-slate-600">{label}</p><p className="mt-1 text-xs text-slate-200">{value == null ? '—' : `$${value.toFixed(2)}`}</p></div>; }
