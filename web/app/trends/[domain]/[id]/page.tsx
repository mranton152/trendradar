import Link from "next/link";
import { notFound } from "next/navigation";

import { ScoreBreakdown } from "@/components/ScoreBreakdown";
import { TimeSeriesChart } from "@/components/TimeSeriesChart";
import { getTrends, type Trend } from "@/lib/api";

const STAGE_LABELS = {
  emerging: "зарождение",
  early_growth: "ранний рост",
  scaling: "масштабирование",
} as const;

type TrendPageProps = {
  params: Promise<{ domain: string; id: string }>;
  searchParams: Promise<{ as_of?: string }>;
};

function selectedYear(value: string | undefined): number {
  const year = Number(value ?? 2026);
  return year === 2021 || year === 2026 ? year : 2026;
}

function Citations({ ids, sources }: { ids: string[]; sources: Trend["sources"] }) {
  const citedSources = sources.filter((source) => ids.includes(source.doc_id));
  if (citedSources.length === 0) return null;

  return (
    <p className="mt-3 text-sm text-slate-500">
      Источники: {citedSources.map((source, index) => (
        <span key={source.doc_id}>
          {index > 0 && ", "}
          <a
            className="text-indigo-600 underline decoration-indigo-300 underline-offset-2 hover:text-indigo-700"
            href={source.url}
            rel="noreferrer"
            target="_blank"
          >
            {source.title}
          </a>
        </span>
      ))}
    </p>
  );
}

export default async function TrendPage({ params, searchParams }: TrendPageProps) {
  const { domain: encodedDomain, id: encodedId } = await params;
  const { as_of: asOfParam } = await searchParams;
  const domain = decodeURIComponent(encodedDomain);
  const trendId = decodeURIComponent(encodedId);
  const asOf = selectedYear(asOfParam);
  const data = await getTrends(domain, asOf);
  const trend = data.trends.find((item) => item.trend_id === trendId);

  if (!trend) {
    notFound();
  }

  return (
    <main className="mx-auto max-w-3xl space-y-9 px-6 py-12">
      <Link
        className="text-sm text-indigo-600 hover:underline"
        href={`/trends/${encodeURIComponent(domain)}?as_of=${data.as_of}`}
      >
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

      {(trend.motivation || trend.case_example) && (
        <section className="space-y-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          {trend.motivation && (
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Зачем это нужно</h2>
              {trend.motivation.problem && (
                <p className="mt-3 text-slate-700">{trend.motivation.problem}</p>
              )}
              {trend.motivation.advantage && (
                <p className="mt-3 text-slate-700">{trend.motivation.advantage}</p>
              )}
              <Citations ids={trend.motivation.sources} sources={trend.sources} />
            </div>
          )}
          {trend.case_example && (
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Кейс-пример</h2>
              <p className="mt-3 font-medium text-slate-900">
                {trend.case_example.type === "company" ? "Компания" : "Исследование"}: {trend.case_example.name}
              </p>
              <p className="mt-2 text-slate-700">{trend.case_example.description}</p>
              <Citations
                ids={trend.case_example.source ? [trend.case_example.source] : []}
                sources={trend.sources}
              />
            </div>
          )}
        </section>
      )}

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
