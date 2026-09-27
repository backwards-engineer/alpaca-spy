'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, FileText, LoaderCircle, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { NewsTimeline, type NewsArticle } from '@/components/news-timeline';
import { SignalLab } from '@/components/signal-lab';
import { CandlestickChart } from '@/components/candlestick-chart';

type Bar = { timestamp: string; open: number; high: number; low: number; close: number; volume: number;
  implied_volatility?: number | null; delta?: number | null; gamma?: number | null; theta?: number | null; vega?: number | null };
type OptionSeries = {
  target_dte: number; actual_dte: number; expiration_date: string; symbol: string;
  option_type: 'call' | 'put'; strike: number; spot: number; side: string;
  rank_from_spot: number; bars: Bar[]; open_interest: number | null; open_interest_date: string | null;
  contract_close: number | null; contract_close_date: string | null;
};
type DayData = {
  market_date: string; underlying: Bar[]; options: OptionSeries[]; note: string;
  previous_close: number | null;
  note_updated_at: string | null; previous_day: string | null; next_day: string | null;
  news: NewsArticle[]; resolution: { underlying: string; options: string };
};

function UnderlyingChart({ bars, open }: { bars: Bar[]; open: number }) {
  return <CandlestickChart candles={bars} referencePrice={open} timeLabel={timeLabel} className="h-[240px] w-full" ariaLabel="SPY intraday candlestick chart" />;
}

function timeLabel(timestamp: string) {
  return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }).format(new Date(timestamp));
}

function sessionLabel(date: string) {
  return new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`));
}

function MiniOption({ option }: { option: OptionSeries }) {
  const values = option.bars.map((bar) => bar.close);
  const first = values[0], last = values.at(-1);
  const change = first && last ? ((last / first) - 1) * 100 : null;
  const latestMetric = [...option.bars].reverse().find((bar) => bar.implied_volatility != null);
  const moneyness = option.option_type === 'call'
    ? option.strike < option.spot ? 'ITM' : 'OTM'
    : option.strike > option.spot ? 'ITM' : 'OTM';
  return (
    <article className="group min-w-0 border border-white/8 bg-[#0a1613] p-2.5 transition hover:border-white/20 hover:bg-[#0e1d19]" title={option.symbol}>
      <div className="flex items-start justify-between gap-2">
        <div><p className="font-mono text-[11px] font-semibold text-slate-200">{option.option_type === 'call' ? 'C' : 'P'} {option.strike.toFixed(0)}</p><p className="font-mono text-[8px] uppercase tracking-wider text-slate-600">{moneyness} · {option.bars.length} bars</p></div>
        <p className={`font-mono text-[9px] ${change == null ? 'text-slate-600' : change >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{change == null ? '—' : `${change >= 0 ? '+' : ''}${change.toFixed(0)}%`}</p>
      </div>
      {option.bars.length ? <CandlestickChart candles={option.bars} compact className="mt-2 h-10 w-full" ariaLabel={`${option.symbol} intraday candlestick chart`} /> : <div className="mt-2 grid h-10 place-items-center font-mono text-[8px] uppercase tracking-widest text-slate-700">No trades</div>}
      <div className="mt-1 flex justify-between font-mono text-[9px] text-slate-500"><span>{first ? `$${first.toFixed(2)}` : '—'}</span><span>{last ? `$${last.toFixed(2)}` : '—'}</span></div>
      <div className="mt-1.5 flex justify-between border-t border-white/5 pt-1.5 font-mono text-[8px] text-slate-600"><span>IV {latestMetric?.implied_volatility != null ? `${(latestMetric.implied_volatility * 100).toFixed(1)}%` : '—'}</span><span>Δ {latestMetric?.delta != null ? latestMetric.delta.toFixed(2) : '—'}</span><span>OI {option.open_interest?.toLocaleString() ?? '—'}</span></div>
    </article>
  );
}

export function DayView({ marketDate, returnMonth }: { marketDate: string; returnMonth: string }) {
  const [data, setData] = useState<DayData | null>(null);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    setData(null); setError('');
    fetch(`/api/day/${marketDate}`).then((response) => { if (!response.ok) throw new Error('Unable to load this session'); return response.json(); })
      .then((result) => { setData(result); setNote(result.note); }).catch((reason) => setError(reason.message));
  }, [marketDate]);

  const stats = useMemo(() => {
    if (!data?.underlying.length) return null;
    const first = data.underlying[0], last = data.underlying.at(-1)!;
    const high = Math.max(...data.underlying.map((bar) => bar.high));
    const low = Math.min(...data.underlying.map((bar) => bar.low));
    const changeBase = data.previous_close ?? first.open;
    return { open: first.open, close: last.close, high, low, change: ((last.close / changeBase) - 1) * 100, volume: data.underlying.reduce((sum, bar) => sum + bar.volume, 0) };
  }, [data]);

  async function saveNote() {
    setSaveState('saving');
    try {
      const response = await fetch(`/api/notes/${marketDate}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) });
      if (!response.ok) throw new Error('save failed');
      setSaveState('saved'); window.setTimeout(() => setSaveState('idle'), 1600);
    } catch { setSaveState('error'); }
  }

  if (error) return <main className="grid min-h-screen place-items-center bg-background text-rose-300">{error}</main>;
  if (!data || !stats) return <main className="grid min-h-screen place-items-center bg-background text-sm text-slate-400"><span><LoaderCircle className="mr-2 inline size-4 animate-spin" />Loading full session</span></main>;

  const dtes = [0, 30, 60, 120];
  const tradedSeries = data.options.filter((option) => option.bars.length > 0).length;
  const missingSeries = data.options.length - tradedSeries;
  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b border-white/8 bg-[#07120f]/95 px-4 py-3 backdrop-blur-xl md:px-7">
        <div className="mx-auto flex max-w-[1800px] items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3"><Button variant="ghost" size="icon" aria-label="Back to calendar" onClick={() => window.location.href = `/?month=${returnMonth}`}><ArrowLeft /></Button><div className="min-w-0"><p className="truncate font-mono text-[9px] uppercase tracking-[0.2em] text-emerald-300/70">SPY session / {marketDate}</p><h1 className="truncate text-base font-semibold md:text-lg">{sessionLabel(marketDate)}</h1></div></div>
          <div className="flex gap-1"><Button variant="outline" size="icon" disabled={!data.previous_day} aria-label="Previous session" onClick={() => data.previous_day && (window.location.search = `day=${data.previous_day}&month=${data.previous_day.slice(0, 7)}`)}><ChevronLeft /></Button><Button variant="outline" size="icon" disabled={!data.next_day} aria-label="Next session" onClick={() => data.next_day && (window.location.search = `day=${data.next_day}&month=${data.next_day.slice(0, 7)}`)}><ChevronRight /></Button></div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1800px] gap-5 px-4 py-5 xl:grid-cols-[minmax(0,1fr)_330px] xl:px-7">
        <div className="min-w-0 space-y-5">
          <section className="border border-white/8 bg-[#0a1613] p-4 md:p-5">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-4"><div><p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">Underlying / {data.resolution.underlying}</p><h2 className="mt-1 text-2xl font-semibold tracking-tight">SPY <span className="font-mono text-slate-300">{stats.close.toFixed(2)}</span></h2></div><div className={`font-mono text-lg font-semibold ${stats.change >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{stats.change >= 0 ? '+' : ''}{stats.change.toFixed(2)}%</div></div>
            <UnderlyingChart bars={data.underlying} open={stats.open} />
            <div className="mt-3 grid grid-cols-5 gap-2 border-t border-white/8 pt-3 font-mono"><Stat label="Open" value={stats.open.toFixed(2)} /><Stat label="High" value={stats.high.toFixed(2)} /><Stat label="Low" value={stats.low.toFixed(2)} /><Stat label="Close" value={stats.close.toFixed(2)} /><Stat label="Volume" value={`${(stats.volume / 1_000_000).toFixed(1)}m`} /></div>
          </section>

          <SignalLab marketDate={marketDate} />

          <NewsTimeline articles={data.news} />

          <section>
            <div className="mb-3"><p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">Option surface / {data.resolution.options}</p><h2 className="mt-1 text-xl font-semibold">All selected contracts <span className="font-mono text-sm font-normal text-slate-500">{tradedSeries}/{data.options.length} with trades</span></h2><p className="mt-2 max-w-3xl text-xs leading-relaxed text-slate-500">IV and Greeks are local Black–Scholes estimates using a 4.25% risk-free rate and 1.2% dividend yield. SPY options are American-style, so treat these as research estimates rather than exchange values.</p>{missingSeries > 0 ? <p className="mt-3 border-l-2 border-amber-200/40 bg-amber-200/[.04] px-3 py-2 text-xs leading-relaxed text-amber-100/70"><span className="font-mono font-semibold text-amber-200">{missingSeries} contracts have no trade bars.</span> Alpaca’s historical bars are trade-derived: a blank series generally means no qualifying trades occurred, or that the selected future expiration had not been listed yet on this date. It does not indicate a failed request when the session is labeled 5Min.</p> : null}</div>
            <div className="space-y-5">{dtes.map((dte) => {
              const group = data.options.filter((option) => option.target_dte === dte);
              const actual = group[0]?.actual_dte;
              const groupTraded = group.filter((option) => option.bars.length > 0).length;
              return <section className="border border-white/8 bg-[#081410]" key={dte}><div className="flex items-center justify-between border-b border-white/8 px-3 py-2"><h3 className="font-mono text-xs font-semibold text-emerald-200">{dte}D TARGET <span className="text-slate-600">/ {actual} actual · {groupTraded}/{group.length} traded</span></h3><span className="font-mono text-[9px] text-slate-600">EXP {group[0]?.expiration_date}</span></div>{(['call', 'put'] as const).map((type) => <div className="border-b border-white/8 last:border-0" key={type}><div className="flex items-center gap-2 px-3 py-2"><span className={`size-1.5 rounded-full ${type === 'call' ? 'bg-emerald-300' : 'bg-amber-300'}`} /><p className="font-mono text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-500">{type}s · strike ascending</p></div><div className="option-grid grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 2xl:grid-cols-12">{group.filter((option) => option.option_type === type).map((option) => <MiniOption option={option} key={option.symbol} />)}</div></div>)}</section>;
            })}</div>
          </section>
        </div>

        <aside className="xl:sticky xl:top-[76px] xl:h-[calc(100vh-96px)]">
          <section className="border border-amber-200/15 bg-[#17170f] p-4"><div className="mb-4 flex items-start justify-between"><div><p className="font-mono text-[10px] uppercase tracking-[0.2em] text-amber-200/60">Research log</p><h2 className="mt-1 flex items-center gap-2 text-lg font-semibold"><FileText className="size-4 text-amber-200" />Day notes</h2></div><span className="font-mono text-[9px] text-slate-600">{marketDate}</span></div><Textarea value={note} onChange={(event) => { setNote(event.target.value); setSaveState('idle'); }} placeholder="What moved the market? Record a thesis, macro event, anomaly, or follow-up…" className="min-h-[260px] resize-y border-amber-200/15 bg-black/10 leading-relaxed placeholder:text-slate-600" /><div className="mt-3 flex items-center justify-between gap-3"><p aria-live="polite" className={`font-mono text-[9px] uppercase tracking-wider ${saveState === 'error' ? 'text-rose-300' : 'text-slate-500'}`}>{saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved locally' : saveState === 'error' ? 'Save failed' : 'SQLite note'}</p><Button onClick={saveNote} disabled={saveState === 'saving'} className="bg-amber-200 text-[#17170f] hover:bg-amber-100"><Save />Save note</Button></div></section>
          <section className="mt-4 border border-white/8 p-4 font-mono text-[10px] leading-relaxed text-slate-500"><p className="mb-2 uppercase tracking-[0.16em] text-slate-400">Reading the grid</p><p>Each cell is one contract. Green candles closed above their open; rose candles closed below it. Calls and puts remain in separate rows. ITM/OTM is calculated against the session selection spot. Empty charts mean the contract had no trade bar at the displayed resolution.</p></section>
        </aside>
      </div>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div><p className="text-[8px] uppercase tracking-wider text-slate-600">{label}</p><p className="mt-1 text-[10px] text-slate-300 md:text-xs">{value}</p></div>;
}
