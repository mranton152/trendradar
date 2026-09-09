import type { Trend } from "@/lib/api";

const LABELS: Record<keyof Trend["components"], string> = {
  novelty: "новизна",
  growth: "рост",
  accel: "ускорение",
  burst: "всплеск",
  diffusion: "распространение",
};

export function ScoreBreakdown({
  components,
}: {
  components: Trend["components"];
}) {
  return (
    <div className="space-y-3">
      {Object.entries(components).map(([key, value]) => (
        <div className="flex items-center gap-3 text-sm" key={key}>
          <span className="w-32 text-slate-600">
            {LABELS[key as keyof Trend["components"]]}
          </span>
          <div className="h-2 flex-1 overflow-hidden rounded bg-slate-100">
            <div
              className="h-full rounded bg-indigo-600"
              style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
            />
          </div>
          <span className="w-12 text-right tabular-nums text-slate-500">
            {value.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  );
}
