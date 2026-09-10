type Methodology = {
  version: string;
  weights: Record<string, number>;
  descriptions: Record<string, string>;
  filters: Record<string, number>;
  validation: unknown;
};

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
      <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">
        TrendRadar
      </p>
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
          {Object.entries(data.filters).map(([key, value]) => (
            <li key={key}>
              <code className="text-slate-500">{key}</code> = {value}
            </li>
          ))}
        </ul>
      </section>

      {data.validation !== null && (
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-900">
            Валидация на историческом срезе
          </h2>
          <pre className="overflow-x-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-100">
            {JSON.stringify(data.validation, null, 2)}
          </pre>
        </section>
      )}
    </main>
  );
}
