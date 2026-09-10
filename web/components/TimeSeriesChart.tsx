"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Trend } from "@/lib/api";

type TimeSeriesChartProps = {
  series: Trend["evidence"]["series"];
  takeoff: number | null;
};

export function TimeSeriesChart({ series, takeoff }: TimeSeriesChartProps) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer height="100%" width="100%">
        <LineChart data={series} margin={{ top: 12, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
          <XAxis dataKey="year" tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} width={44} />
          <Tooltip
            formatter={(value) => [`${value} публикаций`, ""]}
            labelFormatter={(year) => `${year} год`}
          />
          {takeoff && (
            <ReferenceLine
              label={{ fontSize: 11, position: "top", value: "взлёт" }}
              stroke="#b45309"
              x={takeoff}
            />
          )}
          <Line
            dataKey="count"
            dot={false}
            stroke="#4f46e5"
            strokeWidth={2}
            type="monotone"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
