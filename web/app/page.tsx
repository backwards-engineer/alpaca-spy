import { MarketCalendar } from '@/components/market-calendar';

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ day?: string; month?: string }>;
}) {
  const query = await searchParams;
  return <MarketCalendar initialDay={query.day ?? null} initialMonth={query.month ?? query.day?.slice(0, 7) ?? '2026-08'} />;
}
