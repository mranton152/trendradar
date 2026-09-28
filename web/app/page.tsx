"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

const DEFAULT_QUERY = "технологии в ИИ";

export default function HomePage() {
  const router = useRouter();
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = query.trim();

    if (!value) return;
    setError(null);
    setProgress("Запускаем живой поиск…");
    try {
      const started = await fetch("/api/live", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: value }),
      });
      if (!started.ok) throw new Error("Не удалось запустить поиск");
      const { job_id: jobId } = (await started.json()) as { job_id: string };
      const timer = window.setInterval(async () => {
        const response = await fetch(`/api/live/${jobId}`);
        if (!response.ok) return;
        const job = (await response.json()) as { status: string; stage_text: string; domain?: string; error?: string; no_trends?: boolean };
        setProgress(job.stage_text);
        if (job.status === "done" && job.no_trends) {
          window.clearInterval(timer);
          setError("Поиск завершён, но зарождающихся трендов не найдено. Попробуйте уточнить направление.");
        } else if (job.status === "done" && job.domain) {
          window.clearInterval(timer);
          router.push(`/trends/${encodeURIComponent(job.domain)}`);
        }
        if (job.status === "failed") {
          window.clearInterval(timer);
          setProgress(null);
          setError(job.error ?? "Живой поиск завершился ошибкой");
        }
      }, 1500);
    } catch (cause) {
      setProgress(null);
      setError(cause instanceof Error ? cause.message : "Не удалось запустить поиск");
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
      {progress && <p className="mt-5 text-indigo-700" role="status">{progress}</p>}
      {error && <p className="mt-5 text-red-700" role="alert">{error}</p>}
      <Link className="mt-8 w-fit text-sm font-semibold text-indigo-600 hover:underline" href="/methodology">
        Как мы находим тренды →
      </Link>
    </main>
  );
}
