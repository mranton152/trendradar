import Link from "next/link";

import type { Trend } from "@/lib/api";

const STAGES: Record<Trend["stage"], string> = {
  emerging: "зарождение",
  early_growth: "ранний рост",
  scaling: "масштабирование",
};

const CONFIDENCE: Record<Trend["confidence"], string> = {
  high: "высокая уверенность",
  medium: "средняя уверенность",
  low: "мало данных",
};

type TrendCardProps = {
  trend: Trend;
  domain: string;
  asOf: number;
};

export function TrendCard({ trend, domain, asOf }: TrendCardProps) {
  return (
    <Link
      className="block rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-indigo-400 hover:shadow-md focus:outline-none focus:ring-4 focus:ring-indigo-100"
      href={`/trends/${encodeURIComponent(domain)}/${encodeURIComponent(trend.trend_id)}?as_of=${asOf}`}
    >
      <div className="flex items-baseline gap-4">
        <span className="text-sm tabular-nums text-slate-400">#{trend.rank}</span>
        <h2 className="flex-1 text-lg font-semibold text-slate-950">
          {trend.title}
          {trend.label_en && trend.label_en.toLowerCase() !== trend.title.toLowerCase() && (
            <span className="ml-2 text-sm font-normal text-slate-400">{trend.label_en}</span>
          )}
        </h2>
        <span className="text-sm tabular-nums text-slate-600">
          оценка {trend.confidence_pct}%
        </span>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600">
        <span>взлёт {trend.evidence.takeoff_year ?? "—"}</span>
        <span>{trend.evidence.n_docs} {trend.series_granularity === "month" ? "упоминаний" : "публикаций"}</span>
        <span>{trend.evidence.n_countries} {trend.series_granularity === "month" ? "изданий" : "стран"}</span>
        <span className="text-slate-400">{STAGES[trend.stage]}</span>
        {trend.confidence !== "high" && (
          <span className="text-amber-700">{CONFIDENCE[trend.confidence]}</span>
        )}
      </div>
    </Link>
  );
}
