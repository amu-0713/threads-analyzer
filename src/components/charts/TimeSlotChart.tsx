"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Metrics } from "@/lib/types";

const COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

/** Posts per weekday, stacked by time slot (Asia/Taipei). */
export default function TimeSlotChart({ dist }: { dist: Metrics["time_distribution"] }) {
  const data = dist.weekdays.map((d, i) => ({
    day: d,
    ...Object.fromEntries(dist.slots.map((s, j) => [s, dist.counts[i][j]])),
  }));
  return (
    <div role="img" aria-label="各星期各時段的發文篇數（下方有表格版本）" style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis dataKey="day" tick={{ fill: "var(--chart-text)", fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis allowDecimals={false} tick={{ fill: "var(--chart-text)", fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={{ background: "var(--background)", border: "1px solid var(--chart-grid)", fontSize: 12 }} cursor={{ fill: "var(--chart-grid)" }} />
          <Legend itemSorter={null} wrapperStyle={{ fontSize: 12, color: "var(--chart-text)" }} />
          {dist.slots.map((s, j) => (
            <Bar key={s} isAnimationActive={false} dataKey={s} stackId="a" fill={COLORS[j]} stroke="var(--background)" strokeWidth={2} radius={j === dist.slots.length - 1 ? [4, 4, 0, 0] : 0} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
