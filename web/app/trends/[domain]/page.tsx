import { TrendCard } from "@/components/TrendCard";
import { getTrends } from "@/lib/api";

type TrendsPageProps = {
  params: Promise<{ domain: string }>;
  searchParams: Promise<{ as_of?: string }>;
};

function selectedYear(value: string | undefined): number {
  const year = Number(value ?? 2026);
  return Number.isInteger(year) && year >= 1900 && year <= 2100 ? year : 2026;
}

export default async function TrendsPage({
  params,
  searchParams,
}: TrendsPageProps) {
  const { domain: encodedDomain } = await params;
  const { as_of: asOfParam } = await searchParams;
  const domain = decodeURIComponent(encodedDomain);
  const data = await getTrends(domain, selectedYear(asOfParam));

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">
        TrendRadar
      </p>
      <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-950">
        ТОП-{data.trends.length}: {data.domain.query}
      </h1>
      <p className="mt-2 text-sm text-slate-500">
        срез {data.as_of} · методология {data.methodology_version}
      </p>
      <div className="mt-8 space-y-3">
        {data.trends.map((trend) => (
          <TrendCard domain={domain} key={trend.trend_id} trend={trend} />
        ))}
      </div>
    </main>
  );
}
