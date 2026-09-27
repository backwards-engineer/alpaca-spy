'use client';

export type Candle = {
  timestamp?: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

type Props = {
  candles: Candle[];
  compact?: boolean;
  className?: string;
  ariaLabel: string;
  referencePrice?: number;
  timeLabel?: (timestamp: string) => string;
};

export function CandlestickChart({ candles, compact = false, className = '', ariaLabel, referencePrice, timeLabel }: Props) {
  if (!candles.length) return <div className={className} />;

  const width = compact ? 100 : 1000;
  const height = compact ? 36 : 230;
  const left = compact ? 2 : 54;
  const right = compact ? 2 : 26;
  const topPad = compact ? 3 : 12;
  const bottom = compact ? 3 : 28;
  const plotWidth = width - left - right;
  const plotHeight = height - topPad - bottom;
  const rawLow = Math.min(...candles.map((bar) => bar.low), referencePrice ?? Infinity);
  const rawHigh = Math.max(...candles.map((bar) => bar.high), referencePrice ?? -Infinity);
  const padding = Math.max((rawHigh - rawLow) * (compact ? 0.08 : 0.12), Math.abs(rawHigh) * 0.0005, 0.01);
  const low = rawLow - padding;
  const high = rawHigh + padding;
  const range = high - low || 1;
  const step = plotWidth / Math.max(candles.length, 1);
  const bodyWidth = Math.max(compact ? 0.45 : 0.8, Math.min(compact ? 2.1 : 5, step * 0.62));
  const x = (index: number) => left + step * (index + 0.5);
  const y = (value: number) => topPad + ((high - value) / range) * plotHeight;
  const ticks = [0, .25, .5, .75, 1];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className={className} role="img" aria-label={ariaLabel}>
      {!compact && ticks.map((fraction) => {
        const value = high - range * fraction;
        return <g key={fraction}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} stroke="rgba(255,255,255,.07)" strokeDasharray="2 5" /><text x="2" y={y(value) + 4} fill="#64748b" fontSize="11" fontFamily="monospace">{value.toFixed(2)}</text></g>;
      })}
      {referencePrice != null ? <line x1={left} x2={width - right} y1={y(referencePrice)} y2={y(referencePrice)} stroke="#94a3b8" strokeOpacity=".45" strokeDasharray="5 5" /> : null}
      {candles.map((bar, index) => {
        const rising = bar.close >= bar.open;
        const color = rising ? '#36d399' : '#fb7185';
        const bodyTop = y(Math.max(bar.open, bar.close));
        const bodyBottom = y(Math.min(bar.open, bar.close));
        return <g key={bar.timestamp ?? index}>
          <line x1={x(index)} x2={x(index)} y1={y(bar.high)} y2={y(bar.low)} stroke={color} strokeWidth={compact ? .65 : 1} vectorEffect="non-scaling-stroke" />
          <rect x={x(index) - bodyWidth / 2} y={bodyTop} width={bodyWidth} height={Math.max(bodyBottom - bodyTop, compact ? .65 : 1.1)} fill={rising ? '#153f32' : '#4b1f2b'} stroke={color} strokeWidth={compact ? .5 : .8} vectorEffect="non-scaling-stroke">
            <title>{bar.timestamp && timeLabel ? `${timeLabel(bar.timestamp)} · ` : ''}O ${bar.open.toFixed(2)} H ${bar.high.toFixed(2)} L ${bar.low.toFixed(2)} C ${bar.close.toFixed(2)}</title>
          </rect>
        </g>;
      })}
      {!compact && timeLabel && ticks.map((fraction) => {
        const index = Math.min(candles.length - 1, Math.round((candles.length - 1) * fraction));
        const timestamp = candles[index].timestamp;
        return timestamp ? <text key={fraction} x={x(index)} y={height - 4} textAnchor={fraction === 0 ? 'start' : fraction === 1 ? 'end' : 'middle'} fill="#64748b" fontSize="10" fontFamily="monospace">{timeLabel(timestamp).replace(' ', '')}</text> : null;
      })}
    </svg>
  );
}
