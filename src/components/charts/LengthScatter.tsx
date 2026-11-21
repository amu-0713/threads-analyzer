"use client";

import { CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";

export type Pt = { x: number; y: number; url: string; source: "real" | "mock" };

/** Text length vs interaction rate, one dot per post. Real = blue, mock = orange (mock only appears in the "all" scope). */
export default function LengthScatter({ points }: { points: Pt[] }) {
  const real = points.filter((p) => p.source === "real");
  const mock = points.filter((p) => p.source === "mock");
  return (
    <div role="img" aria-label="文長與互動率的散佈圖" style={{ width: "100%", height: 300 }}>
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 0, right: 16, bottom: 16, left: -8 }}>
          <CartesianGrid stroke="var(--chart-grid)" />
          <XAxis type="number" dataKey="x" name="字數" tick={{ fill: "var(--chart-text)", fontSize: 12 }} axisLine={false} tickLine={false}
            label={{ value: "字數", position: "insideBottom", offset: -8, fill: "var(--chart-text)", fontSize: 12 }} />
          <YAxis type="number" dataKey="y" name="互動率" unit="%" tick={{ fill: "var(--chart-text)", fontSize: 12 }} axisLine={false} tickLine={false} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={{ background: "var(--background)", border: "1px solid var(--chart-grid)", fontSize: 12 }}
            formatter={(v, n) => [n === "互動率" ? `${Number(v).toFixed(2)}%` : v, n]} />
          <Legend verticalAlign="top" itemSorter={null} wrapperStyle={{ fontSize: 12, color: "var(--chart-text)" }} />
          <Scatter isAnimationActive={false} name="真實貼文" data={real} fill="var(--series-1)" stroke="var(--background)" strokeWidth={2} />
          {mock.length > 0 && <Scatter isAnimationActive={false} name="模擬貼文（mock）" data={mock} fill="var(--series-2)" stroke="var(--background)" strokeWidth={2} />}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
