import Link from "next/link";

import { AsOfSwitch } from "@/components/AsOfSwitch";
import { TrendCard } from "@/components/TrendCard";
import { getAvailableDomains, getTrends } from "@/lib/api";

const AVAILABLE_YEARS = [2021, 2026];

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
  let data;
  try {
    data = await getTrends(domain, selectedYear(asOfParam));
  } catch {
    const availableDomains = await getAvailableDomains();
    return (
      <main className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="text-3xl font-bold tracking-tight text-slate-950">Направление пока не найдено</h1>
        <p className="mt-3 text-slate-600">
          Выберите доступное направление или дождитесь живого поиска.
        </p>
        {availableDomains.length > 0 ? (
          <ul className="mt-6 space-y-2">
            {availableDomains.map((availableDomain) => (
              <li key={availableDomain}>
                <Link className="text-indigo-600 hover:underline" href={`/trends/${encodeURIComponent(availableDomain)}`}>
                  {availableDomain}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-6 text-slate-500">Доступных направлений пока нет.</p>
        )}
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">
          TrendRadar
        </p>
        <Link className="text-sm font-semibold text-indigo-600 hover:underline" href="/methodology">
          Методология
        </Link>
      </div>
      <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-950">
        ТОП-{data.trends.length}: {data.domain.query}
      </h1>
      <p className="mt-2 text-sm text-slate-500">
        срез {data.as_of} · методология {data.methodology_version}
      </p>
      <dl className="mt-6 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <dt className="text-sm text-slate-500">Обработано источников</dt>
          <dd className="mt-1 text-2xl font-semibold text-slate-950">{data.stats.n_sources_polled}</dd>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <dt className="text-sm text-slate-500">Найдено кандидатов</dt>
          <dd className="mt-1 text-2xl font-semibold text-slate-950">{data.stats.n_candidates}</dd>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <dt className="text-sm text-slate-500">Сигналов с уверенностью &gt;75%</dt>
          <dd className="mt-1 text-2xl font-semibold text-slate-950">{data.stats.n_confident}</dd>
        </div>
      </dl>
      <div className="mt-5">
        <AsOfSwitch current={data.as_of} domain={domain} years={AVAILABLE_YEARS} />
      </div>
      <div className="mt-8 space-y-3">
        {data.trends.map((trend) => (
          <TrendCard asOf={data.as_of} domain={domain} key={trend.trend_id} trend={trend} />
        ))}
      </div>
      {data.rejected.length > 0 && (
        <details className="mt-8 rounded-xl border border-slate-200 bg-white p-5">
          <summary className="cursor-pointer font-semibold text-slate-900">
            Исключено: {data.rejected.length} кандидатов
          </summary>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-slate-500">
                <tr><th className="pb-2 pr-4 font-medium">Кандидат</th><th className="pb-2 pr-4 font-medium">Причина</th><th className="pb-2 font-medium">Документов</th></tr>
              </thead>
              <tbody>
                {data.rejected.map((candidate) => (
                  <tr className="border-b border-slate-100 last:border-0" key={`${candidate.label}-${candidate.reason}`}>
                    <td className="py-3 pr-4 font-medium text-slate-900">{candidate.label}</td>
                    <td className="py-3 pr-4 text-slate-600">{candidate.reason}</td>
                    <td className="py-3 tabular-nums text-slate-600">{candidate.n_docs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </main>
  );
}
