'use client';

import { useMemo, useRef, useState } from 'react';
import { Rotate3D } from 'lucide-react';

export type SurfaceRow = {
  timestamp: string;
  symbol: string;
  option_type: 'call' | 'put';
  strike: number;
  implied_volatility: number | null;
  volume: number;
};

type Props<T extends SurfaceRow> = {
  rows: T[];
  optionType: 'call' | 'put';
  selectedSymbol: string | null;
  selectedTimestamp: string | null;
  onSelect: (row: T) => void;
};

type Point<T> = { x: number; y: number; depth: number; row: T; level: number };

export function OptionSurface3D<T extends SurfaceRow>({ rows, optionType, selectedSymbol, selectedTimestamp, onSelect }: Props<T>) {
  const [rotation, setRotation] = useState(-38);
  const [elevation, setElevation] = useState(.48);
  const start = useRef<{ x: number; y: number; rotation: number; elevation: number } | null>(null);
  const moved = useRef(false);

  const model = useMemo(() => {
    const source = rows.filter((row) => row.option_type === optionType && row.implied_volatility != null);
    const allTimes = [...new Set(source.map((row) => row.timestamp))].sort();
    const stride = Math.max(1, Math.ceil(allTimes.length / 28));
    const times = allTimes.filter((_, index) => index % stride === 0 || index === allTimes.length - 1);
    const strikes = [...new Set(source.map((row) => row.strike))].sort((a, b) => a - b);
    const map = new Map(source.map((row) => [`${row.timestamp}|${row.strike}`, row]));
    const ivs = source.map((row) => row.implied_volatility!).sort((a, b) => a - b);
    const quantile = (portion: number) => ivs[Math.min(ivs.length - 1, Math.floor((ivs.length - 1) * portion))] ?? 0;
    const low = quantile(.05);
    const high = Math.max(low + .01, quantile(.95));
    return { times, strikes, map, low, high };
  }, [rows, optionType]);

  const angle = rotation * Math.PI / 180;
  const project = (time: number, strike: number, height: number) => {
    const worldX = time * 285;
    const worldZ = strike * 185;
    const worldY = -height * 145;
    const rotatedX = worldX * Math.cos(angle) - worldZ * Math.sin(angle);
    const depth = worldX * Math.sin(angle) + worldZ * Math.cos(angle);
    return { x: 400 + rotatedX, y: 286 + depth * elevation + worldY, depth };
  };

  const grid = useMemo(() => model.times.map((timestamp, timeIndex) => model.strikes.map((strike, strikeIndex) => {
    const row = model.map.get(`${timestamp}|${strike}`) as T | undefined;
    if (!row || row.implied_volatility == null) return null;
    const level = Math.max(0, Math.min(1, (row.implied_volatility - model.low) / (model.high - model.low)));
    const point = project(
      model.times.length < 2 ? 0 : (timeIndex / (model.times.length - 1)) * 2 - 1,
      model.strikes.length < 2 ? 0 : (strikeIndex / (model.strikes.length - 1)) * 2 - 1,
      .08 + level * .92,
    );
    return { ...point, row, level } as Point<T>;
  })), [model, angle, elevation]);

  const cells = useMemo(() => {
    const result: { points: Point<T>[]; depth: number; row: T; level: number }[] = [];
    for (let time = 0; time < grid.length - 1; time += 1) {
      for (let strike = 0; strike < (grid[time]?.length ?? 0) - 1; strike += 1) {
        const points = [grid[time][strike], grid[time + 1][strike], grid[time + 1][strike + 1], grid[time][strike + 1]];
        if (points.every(Boolean)) {
          const complete = points as Point<T>[];
          result.push({ points: complete, depth: complete.reduce((sum, point) => sum + point.depth, 0) / 4,
            row: complete[0].row, level: complete.reduce((sum, point) => sum + point.level, 0) / 4 });
        }
      }
    }
    return result.sort((a, b) => a.depth - b.depth);
  }, [grid]);

  const floor = [project(-1, -1, 0), project(1, -1, 0), project(1, 1, 0), project(-1, 1, 0)];
  const selectedPoint = grid.flat().filter(Boolean).find((point) => point!.row.symbol === selectedSymbol && point!.row.timestamp === selectedTimestamp) ?? null;
  const base = optionType === 'call' ? [54, 211, 153] : [251, 191, 36];
  const timeStart = model.times[0];
  const timeEnd = model.times.at(-1);

  if (model.times.length < 2 || model.strikes.length < 2 || !cells.length) {
    return <div className="grid h-[390px] place-items-center border border-white/8 bg-black/10 font-mono text-[10px] uppercase tracking-wider text-slate-600">Not enough IV observations to form a surface</div>;
  }

  return <div className="relative overflow-hidden border border-white/8 bg-[radial-gradient(circle_at_50%_25%,rgba(34,211,238,.07),transparent_52%),#06110f]">
    <div className="pointer-events-none absolute left-3 top-3 z-10 flex items-center gap-2 border border-cyan-200/15 bg-[#071513]/85 px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-wider text-cyan-100/70 backdrop-blur"><Rotate3D className="size-3.5" />Drag to orbit · click to inspect</div>
    <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex gap-3 font-mono text-[9px] text-slate-500"><span>{timeStart ? shortTime(timeStart) : '—'}</span><span className="text-cyan-200/60">TIME</span><span>{timeEnd ? shortTime(timeEnd) : '—'}</span></div>
    <div className="pointer-events-none absolute bottom-3 right-3 z-10 font-mono text-[9px] text-slate-500">IV {(model.low * 100).toFixed(1)}–{(model.high * 100).toFixed(1)}%</div>
    <svg viewBox="0 0 800 380" className="h-[390px] w-full cursor-grab touch-none active:cursor-grabbing" role="img" aria-label={`${optionType} implied volatility surface by session time and strike`}
      onPointerDown={(event) => { start.current = { x: event.clientX, y: event.clientY, rotation, elevation }; moved.current = false; event.currentTarget.setPointerCapture(event.pointerId); }}
      onPointerMove={(event) => { if (!start.current) return; const dx = event.clientX - start.current.x; const dy = event.clientY - start.current.y; if (Math.abs(dx) + Math.abs(dy) > 3) moved.current = true; setRotation(start.current.rotation + dx * .35); setElevation(Math.max(.18, Math.min(.82, start.current.elevation + dy * .003))); }}
      onPointerUp={(event) => { start.current = null; event.currentTarget.releasePointerCapture(event.pointerId); }}>
      <polygon points={floor.map((point) => `${point.x},${point.y}`).join(' ')} fill="rgba(255,255,255,.018)" stroke="rgba(148,163,184,.18)" strokeWidth="1" />
      {[-.5, 0, .5].map((position) => { const a = project(position, -1, 0), b = project(position, 1, 0); return <line key={`t${position}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="rgba(148,163,184,.09)" />; })}
      {[-.5, 0, .5].map((position) => { const a = project(-1, position, 0), b = project(1, position, 0); return <line key={`s${position}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="rgba(148,163,184,.09)" />; })}
      {cells.map((cell, index) => {
        const alpha = .24 + cell.level * .48;
        const fill = `rgba(${base[0]},${base[1]},${base[2]},${alpha})`;
        const stroke = `rgba(${base[0]},${base[1]},${base[2]},${Math.min(.8, alpha + .16)})`;
        return <polygon key={`${cell.row.timestamp}-${cell.row.strike}-${index}`} points={cell.points.map((point) => `${point.x},${point.y}`).join(' ')} fill={fill} stroke={stroke} strokeWidth=".65" vectorEffect="non-scaling-stroke" onClick={() => { if (moved.current) { moved.current = false; return; } onSelect(cell.row); }} className="cursor-crosshair"><title>{shortTime(cell.row.timestamp)} · strike {cell.row.strike} · IV {(cell.row.implied_volatility! * 100).toFixed(1)}%</title></polygon>;
      })}
      {selectedPoint ? <g><circle cx={selectedPoint.x} cy={selectedPoint.y} r="6" fill="#f8fafc" fillOpacity=".95" /><circle cx={selectedPoint.x} cy={selectedPoint.y} r="11" fill="none" stroke="#f8fafc" strokeOpacity=".45" /></g> : null}
      <text x="400" y="26" textAnchor="middle" fill="#94a3b8" fontFamily="monospace" fontSize="10">IMPLIED VOLATILITY ↑</text>
      <text x="742" y="350" textAnchor="end" fill="#64748b" fontFamily="monospace" fontSize="9">STRIKE →</text>
    </svg>
  </div>;
}

function shortTime(timestamp: string) {
  return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }).format(new Date(timestamp));
}
