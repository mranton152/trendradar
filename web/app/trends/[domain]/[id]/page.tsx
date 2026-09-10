import Link from "next/link";
import { notFound } from "next/navigation";

import { ScoreBreakdown } from "@/components/ScoreBreakdown";
import { TimeSeriesChart } from "@/components/TimeSeriesChart";
import { getTrends } from "@/lib/api";

const STAGE_LABELS = {
  emerging: "зарождение",
  early_growth: "ранний рост",
  scaling: "масштабирование",
} as const;

type TrendPageProps = {
  params: Promise<{ domain: string; id: string }>;
};

export default async function TrendPage({ params }: TrendPageProps) {
  const { domain: encodedDomain, id: encodedId } = await params;
  const domain = decodeURIComponent(encodedDomain);
  const trendId = decodeURIComponent(encodedId);
  const data = await getTrends(domain, 2026);
  const trend = data.trends.find((item) => item.trend_id === trendId);

  if (!trend) {
    notFound();
  }

  return (
    <main className="mx-auto max-w-3xl space-y-9 px-6 py-12">
      <Link className="text-sm text-indigo-600 hover:underline" href={`/trends/${encodeURIComponent(domain)}`}>
        ← К списку трендов
      </Link>
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">
          #{trend.rank} · {STAGE_LABELS[trend.stage]}
        </p>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-950">
          {trend.title}
        </h1>
        <p className="mt-3 text-sm text-slate-500">
          Emergence Score {trend.emergence_score.toFixed(3)} · взлёт{" "}
          {trend.evidence.takeoff_year ?? "—"} · первое упоминание{" "}
          {trend.evidence.first_mention ?? "—"}
        </p>
      </header>

      <section>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">Динамика публикаций</h2>
        <TimeSeriesChart
          series={trend.evidence.series}
          takeoff={trend.evidence.takeoff_year}
        />
      </section>

      <section>
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Из чего сложился скор</h2>
        <ScoreBreakdown components={trend.components} />
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">
          Источники ({trend.sources.length})
        </h2>
        {trend.sources.length === 0 ? (
          <p className="text-sm text-slate-500">Для этого тренда источники пока не собраны.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {trend.sources.map((source) => (
              <li key={source.doc_id}>
                <a
                  className="text-slate-900 underline decoration-indigo-300 underline-offset-2 hover:text-indigo-700"
                  href={source.url}
                  rel="noreferrer"
                  target="_blank"
                >
                  {source.title}
                </a>
                <span className="ml-2 tabular-nums text-slate-400">{source.year}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
