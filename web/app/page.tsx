"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

const DEFAULT_QUERY = "технологии в ИИ";

export default function HomePage() {
  const router = useRouter();
  const [query, setQuery] = useState(DEFAULT_QUERY);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = query.trim();

    if (value) {
      router.push(`/trends/${encodeURIComponent(value)}`);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center px-6 py-16">
      <p className="mb-4 text-sm font-semibold uppercase tracking-[0.2em] text-indigo-600">
        TrendRadar
      </p>
      <h1 className="max-w-2xl text-4xl font-bold tracking-tight text-slate-950 sm:text-6xl">
        Какие технологии действительно набирают силу?
      </h1>
      <p className="mt-6 max-w-xl text-lg leading-8 text-slate-600">
        Находим тренды в научных публикациях и показываем путь от оценки до первоисточника.
      </p>

      <form className="mt-10 flex max-w-xl gap-3" onSubmit={submit}>
        <label className="sr-only" htmlFor="trend-query">
          Тема для поиска трендов
        </label>
        <input
          className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-950 outline-none transition focus:border-indigo-600 focus:ring-4 focus:ring-indigo-100"
          id="trend-query"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Например, технологии в ИИ"
          value={query}
        />
        <button
          className="rounded-xl bg-indigo-600 px-5 py-3 font-semibold text-white transition hover:bg-indigo-700 focus:outline-none focus:ring-4 focus:ring-indigo-200"
          type="submit"
        >
          Найти
        </button>
      </form>
    </main>
  );
}
