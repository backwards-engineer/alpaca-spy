'use client';

import { Clock3, ExternalLink, Landmark, Newspaper } from 'lucide-react';

export type NewsArticle = {
  article_id: string; window_key: string; window_rank: number; published_at: string;
  headline: string; summary: string; author: string | null; source: string | null;
  url: string | null; categories: string[]; matched_keywords: string[];
  relevance_score: number;
};

const windows = [
  { key: 'pre_market', label: 'Pre-market slot', time: '7:00–10:15 AM' },
  { key: 'late_morning', label: 'Late-morning slot', time: '10:15 AM–1:00 PM' },
  { key: 'afternoon', label: 'Fed-window slot', time: '1:00–3:30 PM' },
  { key: 'after_close', label: 'After-close slot', time: '3:30–8:00 PM' },
];

const categoryStyle: Record<string, string> = {
  fed: 'border-sky-300/20 bg-sky-300/8 text-sky-200',
  trump: 'border-violet-300/20 bg-violet-300/8 text-violet-200',
  inflation: 'border-rose-300/20 bg-rose-300/8 text-rose-200',
  jobs: 'border-amber-300/20 bg-amber-300/8 text-amber-200',
};

function timeLabel(timestamp: string) {
  return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }).format(new Date(timestamp));
}

export function NewsTimeline({ articles = [] }: { articles?: NewsArticle[] }) {
  return (
    <section className="border border-white/8 bg-[#0a1613]">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-white/8 px-4 py-4 md:px-5">
        <div><p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">Macro catalyst wire</p><h2 className="mt-1 flex items-center gap-2 text-xl font-semibold"><Landmark className="size-5 text-sky-200" />News by market window</h2></div>
        <p className="max-w-md text-right text-xs leading-relaxed text-slate-500">Continuous 7 AM–8 PM coverage. Gap stories are assigned to the nearest slot, then filtered for Fed, Trump, inflation, and labor catalysts.</p>
      </div>
      <div className="grid gap-px bg-white/8 xl:grid-cols-4">
        {windows.map((window) => {
          const items = articles.filter((article) => article.window_key === window.key);
          return (
            <section className="min-w-0 bg-[#081410]" key={window.key}>
              <header className="flex items-center justify-between border-b border-white/8 px-3 py-3">
                <div><h3 className="font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-300">{window.label}</h3><p className="mt-0.5 font-mono text-[9px] text-slate-600">{window.time} ET</p></div>
                <span className="grid size-6 place-items-center rounded-full border border-white/8 font-mono text-[9px] text-slate-400">{items.length}</span>
              </header>
              <div className="divide-y divide-white/8">
                {items.length ? items.map((article) => (
                  <article className="p-3.5" key={article.article_id}>
                    <div className="mb-2 flex flex-wrap items-center gap-1.5">
                      <span className="inline-flex items-center gap-1 font-mono text-[9px] text-slate-500"><Clock3 className="size-3" />{timeLabel(article.published_at)}</span>
                      {article.categories.map((category) => <span className={`border px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wider ${categoryStyle[category] ?? 'border-white/10 text-slate-400'}`} key={category}>{category}</span>)}
                    </div>
                    <h4 className="text-[13px] font-semibold leading-snug text-slate-100">
                      {article.url ? <a href={article.url} target="_blank" rel="noreferrer" className="transition hover:text-emerald-200">{article.headline}<ExternalLink className="ml-1 inline size-3 align-[-1px] text-slate-600" /></a> : article.headline}
                    </h4>
                    {article.summary ? <p className="mt-2 line-clamp-3 text-[11px] leading-relaxed text-slate-500">{article.summary}</p> : null}
                    <div className="mt-2.5 flex items-end justify-between gap-2 font-mono text-[8px] text-slate-600"><span className="truncate">{article.source ?? article.author ?? 'news wire'}</span><span className="shrink-0">score {article.relevance_score}</span></div>
                    <p className="mt-1.5 line-clamp-1 font-mono text-[8px] text-slate-700">matched: {article.matched_keywords.join(' · ')}</p>
                  </article>
                )) : <div className="grid min-h-28 place-items-center px-5 py-8 text-center"><div><Newspaper className="mx-auto mb-2 size-4 text-slate-700" /><p className="font-mono text-[9px] uppercase tracking-wider text-slate-700">No relevant matches</p></div></div>}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}
