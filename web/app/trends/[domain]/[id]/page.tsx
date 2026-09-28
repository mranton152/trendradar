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

const SOURCE_TYPE_LABELS: Record<string, string> = {
  article: "статья",
  preprint: "препринт",
  patent: "патент",
  news: "новость",
  blog: "блог",
  repo: "репозиторий",
  model: "модель",
  report: "отчёт",
  aggregator: "агрегатор",
  press_release: "пресс-релиз",
};

const TRUST_LEVELS = {
  trusted: {
    label: "доверенный источник",
    className: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  },
  indicator: {
    label: "только индикатор",
    className: "bg-amber-50 text-amber-800 ring-amber-200",
  },
  unknown: {
    label: "доверенность не определена",
    className: "bg-slate-100 text-slate-700 ring-slate-200",
  },
} as const;

function languageLabel(lang: string | null): string {
  if (lang === "ru") return "русский";
  if (lang === "en") return "английский";
  return lang ?? "не указан";
}

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
      <nav aria-label="Навигация" className="flex flex-wrap items-center justify-between gap-3 text-sm font-semibold">
        <Link
          className="text-indigo-600 hover:underline"
          href={`/trends/${encodeURIComponent(domain)}?as_of=${data.as_of}`}
        >
          ← К списку трендов
        </Link>
        <Link className="text-indigo-600 hover:underline" href="/">
          Новый поиск
        </Link>
      </nav>
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">
          #{trend.rank} · {STAGE_LABELS[trend.stage]}
        </p>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-950">
          {trend.title}
        </h1>
        <p className="mt-3 text-sm text-slate-500">
          Оценка зарождения {trend.confidence_pct}% · взлёт{" "}
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

      {trend.backtest && (
        <section className="rounded-xl border border-indigo-200 bg-indigo-50 p-6">
          <h2 className="text-lg font-semibold text-slate-900">Что произошло после среза</h2>
          <p className="mt-2 text-slate-700">
            На момент среза — {trend.backtest.at_cutoff} публикаций. Позднейший пик —{" "}
            {trend.backtest.peak_after}; рост в {trend.backtest.growth_x.toFixed(1)} раза.
          </p>
          <p className="mt-2 text-sm text-slate-600">
            Это результат бэктеста: система показывает, как найденный в прошлом сигнал
            развился до текущего периода.
          </p>
        </section>
      )}

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
          <ul className="space-y-3 text-sm">
            {trend.sources.map((source) => (
              <li className="rounded-lg border border-slate-200 bg-white p-4" key={source.doc_id}>
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
                  <a
                    className="font-medium text-slate-900 underline decoration-indigo-300 underline-offset-2 hover:text-indigo-700"
                    href={source.url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    {source.title}
                  </a>
                  {source.trust_level && (
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TRUST_LEVELS[source.trust_level].className}`}
                    >
                      {TRUST_LEVELS[source.trust_level].label}
                    </span>
                  )}
                </div>
                <p className="mt-2 text-slate-600">
                  Опубликовано: {source.date ?? source.year} · Тип: {SOURCE_TYPE_LABELS[source.source_type ?? source.type] ?? source.source_type ?? source.type} · Язык: {languageLabel(source.lang)}
                </p>
                {source.trust_level === "indicator" && (
                  <p className="mt-2 text-amber-800">
                    Этот источник не может быть единственным основанием для вывода.
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
