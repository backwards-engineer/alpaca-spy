'use client';

import { useEffect, useMemo, useState } from 'react';
import { CalendarRange, ChevronLeft, ChevronRight, FileText, LineChart, LoaderCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DayView } from '@/components/day-view';
import { CandlestickChart, type Candle } from '@/components/candlestick-chart';

type CalendarDay = {
  market_date: string; open: number; high: number; low: number; close: number;
  previous_close: number | null;
  change_pct: number; closes: number[]; candles: Candle[]; option_bars: number; option_series: number;
  expected_option_series: number; option_resolution: string; volume: number; news_count: number; has_note: number;
};
type YearMonth = { month: string; sessions: number; open: number; close: number; high: number; low: number;
  change_pct: number; up_days: number; closes: number[]; candles: Candle[]; news_count: number };

const monthLabel = (month: string) => new Intl.DateTimeFormat('en-US', {
  month: 'long', year: 'numeric', timeZone: 'UTC',
}).format(new Date(`${month}-01T12:00:00Z`));

function moveMonth(month: string, amount: number) {
  const date = new Date(`${month}-01T12:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + amount);
  return date.toISOString().slice(0, 7);
}

function CandleThumbnail({ candles, label }: { candles: Candle[]; label: string }) {
  if (!candles?.length) return <div className="h-9" />;
  return <CandlestickChart candles={candles} compact className="h-9 w-full" ariaLabel={label} />;
}

export function MarketCalendar({ initialDay, initialMonth }: { initialDay: string | null; initialMonth: string }) {
  const [month, setMonth] = useState(initialMonth);
  const [days, setDays] = useState<CalendarDay[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [yearMonths, setYearMonths] = useState<YearMonth[]>([]);
  const [yearLoading, setYearLoading] = useState(true);

  const year = month.slice(0, 4);

  function chooseMonth(nextMonth: string) {
    setMonth(nextMonth);
    window.history.replaceState(null, '', `/?month=${nextMonth}`);
  }

  useEffect(() => {
    setLoading(true); setError('');
    fetch(`/api/calendar?month=${month}`)
      .then((response) => { if (!response.ok) throw new Error('Unable to load this month'); return response.json(); })
      .then((data) => setDays(data.days)).catch((reason) => setError(reason.message)).finally(() => setLoading(false));
  }, [month]);

  useEffect(() => {
    setYearLoading(true);
    fetch(`/api/year?year=${year}`).then((response) => response.json())
      .then((data) => setYearMonths(data.months ?? [])).finally(() => setYearLoading(false));
  }, [year]);

  const slots = useMemo(() => {
    const firstDay = new Date(`${month}-01T12:00:00Z`).getUTCDay();
    const count = new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0).getDate();
    const byDate = new Map(days.map((day) => [Number(day.market_date.slice(8, 10)), day]));
    return [...Array(firstDay).fill(null), ...Array.from({ length: count }, (_, index) => ({ dayNumber: index + 1, market: byDate.get(index + 1) }))];
  }, [days, month]);

  const upDays = days.filter((day) => day.change_pct >= 0).length;
  const averageRange = days.length ? days.reduce((sum, day) => sum + ((day.high - day.low) / day.open) * 100, 0) / days.length : 0;

  if (initialDay) return <DayView marketDate={initialDay} returnMonth={month} />;

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b border-white/8 bg-[#07120f]/90 px-5 py-4 backdrop-blur-xl md:px-8">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="grid size-9 place-items-center rounded-md border border-emerald-400/25 bg-emerald-400/10 text-emerald-300"><LineChart className="size-5" /></div>
            <div><p className="font-mono text-[10px] uppercase tracking-[0.22em] text-emerald-300/75">Local research terminal</p><h1 className="text-lg font-semibold tracking-tight">SPY Field Notes</h1></div>
          </div>
          <div className="hidden items-center gap-5 font-mono text-xs text-slate-400 md:flex"><span><b className="text-slate-100">{days.length}</b> sessions</span><span><b className="text-emerald-300">{upDays}</b> green</span><span><b className="text-amber-200">{averageRange.toFixed(2)}%</b> avg range</span></div>
        </div>
      </header>

      <section className="mx-auto max-w-[1500px] px-4 py-6 md:px-8 md:py-8">
        <section className="mb-8 border border-white/8 bg-[#081410]">
          <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
            <div className="flex items-center gap-2"><CalendarRange className="size-4 text-emerald-300" /><div><p className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500">Whole year</p><h2 className="font-mono text-sm font-semibold text-slate-200">{year} month map</h2></div></div>
            <div className="flex items-center gap-1"><Button variant="ghost" size="icon" aria-label="Previous year" onClick={() => chooseMonth(`${Number(year) - 1}-${month.slice(5)}`)}><ChevronLeft /></Button><span className="min-w-12 text-center font-mono text-xs text-slate-400">{year}</span><Button variant="ghost" size="icon" aria-label="Next year" onClick={() => chooseMonth(`${Number(year) + 1}-${month.slice(5)}`)}><ChevronRight /></Button></div>
          </div>
          <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-12">
            {Array.from({ length: 12 }, (_, index) => {
              const key = `${year}-${String(index + 1).padStart(2, '0')}`;
              const item = yearMonths.find((entry) => entry.month === key);
              const selected = key === month;
              const positive = (item?.change_pct ?? 0) >= 0;
              return <button key={key} onClick={() => chooseMonth(key)} className={`min-w-0 border-b border-r border-white/8 p-2.5 text-left transition lg:border-b-0 ${selected ? 'bg-emerald-300/10 ring-1 ring-inset ring-emerald-300/50' : 'hover:bg-white/[.035]'}`} aria-current={selected ? 'date' : undefined}>
                <div className="flex items-center justify-between"><span className={`font-mono text-[10px] uppercase tracking-wider ${selected ? 'text-emerald-200' : 'text-slate-400'}`}>{new Intl.DateTimeFormat('en-US', { month: 'short', timeZone: 'UTC' }).format(new Date(`${key}-01T12:00:00Z`))}</span><span className="font-mono text-[8px] text-slate-600">{item?.sessions ?? 0}d</span></div>
                {yearLoading ? <div className="mt-2 h-7 animate-pulse bg-white/[.03]" /> : item ? <CandleThumbnail candles={item.candles} label={`${key} daily candlestick chart`} /> : <div className="mt-2 grid h-9 place-items-center font-mono text-[8px] text-slate-700">NO DATA</div>}
                <p className={`mt-1 font-mono text-[10px] ${item ? positive ? 'text-emerald-300' : 'text-rose-300' : 'text-slate-700'}`}>{item ? `${positive ? '+' : ''}${item.change_pct.toFixed(1)}%` : '—'}</p>
              </button>;
            })}
          </div>
        </section>

        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div><p className="mb-1 font-mono text-[11px] uppercase tracking-[0.2em] text-slate-500">Session archive</p><h2 className="text-3xl font-semibold tracking-[-0.04em] md:text-4xl">{monthLabel(month)}</h2><p className="mt-2 max-w-xl text-sm text-slate-400">Minute-level SPY candlesticks with exact OHLC range and option-contract coverage. Open a session for the full surface.</p></div>
          <div className="flex items-center gap-2"><Button variant="outline" size="icon" aria-label="Previous month" onClick={() => chooseMonth(moveMonth(month, -1))}><ChevronLeft /></Button><Button variant="outline" className="min-w-24 font-mono" onClick={() => chooseMonth('2026-08')}>Latest</Button><Button variant="outline" size="icon" aria-label="Next month" onClick={() => chooseMonth(moveMonth(month, 1))}><ChevronRight /></Button></div>
        </div>

        <div className="grid grid-cols-7 border-l border-t border-white/8 text-center font-mono text-[10px] uppercase tracking-[0.18em] text-slate-500">{['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((label) => <div className="border-b border-r border-white/8 py-2" key={label}>{label}</div>)}</div>
        {loading ? <div className="grid min-h-[480px] place-items-center border border-t-0 border-white/8 text-sm text-slate-400"><span><LoaderCircle className="mr-2 inline size-4 animate-spin" />Loading sessions</span></div> : error ? <div className="grid min-h-[480px] place-items-center border border-t-0 border-white/8 text-sm text-rose-300">{error}</div> : (
          <div className="calendar-grid grid grid-cols-7 border-l border-white/8">
            {slots.map((slot, index) => {
              if (!slot) return <div className="calendar-cell empty border-b border-r border-white/8" key={`blank-${index}`} />;
              const day = slot.market;
              if (!day) return <div className="calendar-cell empty border-b border-r border-white/8 p-3" key={slot.dayNumber}><span className="font-mono text-xs text-slate-700">{slot.dayNumber}</span></div>;
              const positive = day.change_pct >= 0;
              return <button className="calendar-cell group relative flex flex-col border-b border-r border-white/8 bg-[#0b1714] p-2.5 text-left transition hover:z-10 hover:border-emerald-400/40 hover:bg-[#10231d] focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 md:p-3" key={day.market_date} onClick={() => window.location.search = `day=${day.market_date}&month=${month}`} aria-label={`Open ${day.market_date}, SPY ${positive ? 'up' : 'down'} ${Math.abs(day.change_pct)} percent`}>
                <div className="flex w-full items-start justify-between"><span className="font-mono text-xs text-slate-300">{slot.dayNumber}</span>{day.has_note ? <FileText className="size-3 text-amber-200" /> : null}</div>
                <div className="my-auto w-full py-1"><CandleThumbnail candles={day.candles} label={`${day.market_date} intraday candlestick chart`} /><div className="mt-1 hidden grid-cols-2 gap-x-2 font-mono text-[8px] text-slate-600 md:grid"><span>O {day.open.toFixed(2)}</span><span className="text-right">H {day.high.toFixed(2)}</span><span>L {day.low.toFixed(2)}</span><span className="text-right">C {day.close.toFixed(2)}</span></div></div>
                <div className="flex w-full items-end justify-between gap-1"><div><p className="font-mono text-[9px] text-slate-500">{day.option_series}/{day.expected_option_series} contracts</p><p className="font-mono text-[8px] uppercase text-slate-700">{day.option_resolution} bars · {day.news_count} news</p></div><div className="text-right"><p className={`font-mono text-[11px] font-semibold ${positive ? 'text-emerald-300' : 'text-rose-300'}`}>{positive ? '+' : ''}{day.change_pct.toFixed(2)}%</p><p className="font-mono text-[8px] text-slate-600">range {(((day.high - day.low) / day.open) * 100).toFixed(2)}%</p></div></div>
              </button>;
            })}
          </div>
        )}
      </section>
    </main>
  );
}
