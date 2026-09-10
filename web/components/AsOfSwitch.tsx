"use client";

import { useRouter, useSearchParams } from "next/navigation";

type AsOfSwitchProps = {
  domain: string;
  current: number;
  years: number[];
};

export function AsOfSwitch({ domain, current, years }: AsOfSwitchProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
      <span className="px-2 text-sm text-slate-500">срез</span>
      {years.map((year) => (
        <button
          className={`rounded-lg px-3 py-1.5 text-sm font-semibold tabular-nums transition focus:outline-none focus:ring-4 focus:ring-indigo-100 ${
            year === current
              ? "bg-indigo-600 text-white"
              : "text-slate-600 hover:bg-slate-100"
          }`}
          key={year}
          onClick={() => {
            const params = new URLSearchParams(searchParams.toString());
            params.set("as_of", String(year));
            router.push(`/trends/${encodeURIComponent(domain)}?${params.toString()}`);
          }}
          type="button"
        >
          {year}
        </button>
      ))}
      {current < 2026 && (
        <span className="px-2 text-sm text-amber-700">
          режим бэктеста: что сервис нашёл бы в {current} году
        </span>
      )}
    </div>
  );
}
