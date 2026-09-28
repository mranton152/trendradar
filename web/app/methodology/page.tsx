import Link from "next/link";

type Methodology = {
  version: string;
  weights: Record<string, number>;
  descriptions: Record<string, string>;
  filters: Record<string, number>;
  filter_descriptions?: Record<string, string>;
  live_filter_descriptions?: Record<string, string>;
  classifier?: {
    model: string;
    n: number;
    accuracy: number;
    accuracy_std: number;
    accuracy_min: number;
    accuracy_max: number;
    precision: number;
    recall: number;
    f1: number;
    разбиений: number;
    разбиений_выше_мин: number;
  } | null;
  validation: {
    as_of?: number;
    до_года?: number;
    precision_at_15?: number;
    доля_мейнстрима_в_топе?: number;
    доля_выросших_после_среза?: number;
    медианный_lead_time?: number;
  } | null;
};

const pct = (x: number | undefined) => (x === undefined ? "—" : `${Math.round(x * 100)}%`);

const FALLBACK: Methodology = {
  version: "1.0",
  weights: {
    novelty: 0.2,
    growth: 0.32,
    accel: 0.23,
    burst: 0.15,
    diffusion: 0.1,
  },
  descriptions: {
    novelty: "Новизна: сколько лет прошло с года взлёта.",
    growth: "Рост: наклон логарифма частоты за пятилетнее окно.",
    accel: "Ускорение: разница наклонов второй и первой половины окна.",
    burst: "Всплеск: превышение последнего года над базовой линией.",
    diffusion: "Распространение: сколько разных стран публикует по теме.",
  },
  filters: {
    MIN_EVIDENCE: 20,
    MIN_COUNTRIES: 5,
    MIN_ACTIVE_YEARS: 3,
    MAX_MATURITY_PCT: 0.9,
  },
  validation: null,
};

async function getMethodology(): Promise<Methodology> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!apiUrl) {
    return FALLBACK;
  }

  const response = await fetch(`${apiUrl}/api/v1/methodology`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`TrendRadar API returned ${response.status}`);
  }
  return (await response.json()) as Methodology;
}

export default async function MethodologyPage() {
  const data = await getMethodology();

  return (
    <main className="mx-auto max-w-3xl space-y-9 px-6 py-12">
      <nav aria-label="Навигация" className="flex flex-wrap items-center justify-between gap-4">
        <Link className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600 hover:underline" href="/">TrendRadar</Link>
        <Link className="text-sm font-semibold text-indigo-600 hover:underline" href="/">← К поиску</Link>
      </nav>
      <h1 className="text-3xl font-bold tracking-tight text-slate-950">
        Методология, версия {data.version}
      </h1>

      <section>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">Компоненты и веса</h2>
        <table className="w-full overflow-hidden rounded-xl border border-slate-200 bg-white text-sm shadow-sm">
          <tbody>
            {Object.entries(data.weights).map(([key, weight]) => (
              <tr className="border-b border-slate-100 last:border-0" key={key}>
                <td className="w-20 px-4 py-3 tabular-nums text-slate-500">
                  {weight.toFixed(2)}
                </td>
                <td className="px-4 py-3 text-slate-800">{data.descriptions[key] ?? key}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">
          Фильтры против ложных сигналов
        </h2>
        <ul className="space-y-2 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700 shadow-sm">
          {Object.entries(data.filter_descriptions ?? {}).length > 0
            ? Object.entries(data.filter_descriptions ?? {}).map(([key, text]) => (
                <li key={key}>{text}</li>
              ))
            : Object.entries(data.filters).map(([key, value]) => (
                <li key={key}>
                  <code className="text-slate-500">{key}</code> = {value}
                </li>
              ))}
        </ul>
      </section>

      {data.live_filter_descriptions && (
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-900">
            Живой запрос: новости за 24 месяца
          </h2>
          <ul className="space-y-2 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700 shadow-sm">
            {Object.entries(data.live_filter_descriptions).map(([key, text]) => (
              <li key={key}>{text}</li>
            ))}
          </ul>
        </section>
      )}

      {data.classifier && (
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-900">
            Классификатор на датасете заказчика
          </h2>
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700 shadow-sm">
            <p className="text-2xl font-semibold text-slate-950">
              {(data.classifier.accuracy * 100).toFixed(1)}% ± {(data.classifier.accuracy_std * 100).toFixed(1)}
            </p>
            <p className="mt-1">
              точность, среднее по {data.classifier.разбиений} разбиениям 5-fold;
              диапазон {pct(data.classifier.accuracy_min)}–{pct(data.classifier.accuracy_max)};
              порог ТЗ 75% взят в {data.classifier.разбиений_выше_мин} из {data.classifier.разбиений}
            </p>
            <p className="mt-1 text-slate-500">
              Precision {data.classifier.precision.toFixed(2)} · Recall {data.classifier.recall.toFixed(2)} ·
              F1 {data.classifier.f1.toFixed(2)} · {data.classifier.n} технологий
            </p>
          </div>
        </section>
      )}

      {data.validation && (
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-900">
            Проверка на прошлом: срез {data.validation.as_of} → {data.validation.до_года}
          </h2>
          <dl className="grid gap-3 sm:grid-cols-2">
            {[
              ["Выросли после среза", pct(data.validation.доля_выросших_после_среза)],
              ["Фора обнаружения до пика", `${data.validation.медианный_lead_time ?? "—"} лет`],
              ["Precision@15 по эталону", pct(data.validation.precision_at_15)],
              ["Мейнстрима в ТОПе", pct(data.validation.доля_мейнстрима_в_топе)],
            ].map(([label, value]) => (
              <div className="rounded-xl border border-slate-200 bg-white p-4" key={label}>
                <dt className="text-sm text-slate-500">{label}</dt>
                <dd className="mt-1 text-2xl font-semibold text-slate-950">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
    </main>
  );
}
