"use client";

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BarChart3, Info } from "lucide-react";
import { ChartConfig } from "@/types/agent";

interface DynamicChartProps {
  data: Record<string, unknown>[];
  config: ChartConfig;
}

const PALETTE = [
  "#3b82f6", // Blue
  "#10b981", // Emerald
  "#f59e0b", // Amber
  "#8b5cf6", // Purple
  "#ec4899", // Pink
  "#06b6d4", // Cyan
  "#f97316", // Orange
  "#6366f1", // Indigo
];

export function DynamicChart({ data, config }: DynamicChartProps) {
  // Sanitize data: Coerce numeric values in y_axis_keys to JS numbers
  const sanitizedData = useMemo(() => {
    if (!data || data.length === 0) return [];

    return data.map((row) => {
      const cleanRow: Record<string, unknown> = { ...row };
      config.y_axis_keys.forEach((key) => {
        const rawVal = row[key];
        if (typeof rawVal === "string") {
          const parsed = parseFloat(rawVal);
          cleanRow[key] = isNaN(parsed) ? 0 : parsed;
        } else if (typeof rawVal === "number") {
          cleanRow[key] = rawVal;
        } else {
          cleanRow[key] = 0;
        }
      });
      return cleanRow;
    });
  }, [data, config.y_axis_keys]);

  // Handle empty or chart_type === "none"
  if (
    !data ||
    data.length === 0 ||
    config.chart_type === "none" ||
    config.y_axis_keys.length === 0
  ) {
    return (
      <div className="flex flex-col items-center justify-center h-[340px] text-slate-500 rounded-xl bg-slate-950/40 border border-slate-800/80 p-6 text-center">
        <div className="p-3 rounded-full bg-slate-900 border border-slate-800 text-slate-400 mb-3">
          <BarChart3 className="w-6 h-6" />
        </div>
        <h4 className="text-sm font-medium text-slate-300">
          No chart visualization applicable
        </h4>
        <p className="text-xs text-slate-500 max-w-sm mt-1">
          The query returned a single record or non-numeric dimensional data.
          Switch to the <strong className="text-slate-400">Data Table</strong> tab to view the records.
        </p>
      </div>
    );
  }

  // Handle KPI highlight card
  if (config.chart_type === "kpi" || (data.length === 1 && config.y_axis_keys.length === 1)) {
    const metricKey = config.y_axis_keys[0];
    const rawVal = sanitizedData[0]?.[metricKey];
    const formattedVal =
      typeof rawVal === "number"
        ? rawVal.toLocaleString("en-US", { maximumFractionDigits: 2 })
        : String(rawVal ?? "—");

    return (
      <div className="flex flex-col items-center justify-center h-[340px] rounded-xl bg-gradient-to-b from-slate-900 to-slate-950 border border-slate-800 p-8 text-center">
        <span className="text-xs font-semibold tracking-wider uppercase text-blue-400 mb-2">
          {config.title || metricKey}
        </span>
        <div className="text-5xl font-extrabold tracking-tight text-white my-3 drop-shadow-md">
          {formattedVal}
        </div>
        <p className="text-xs text-slate-400 max-w-sm flex items-center justify-center gap-1.5 mt-2">
          <Info className="w-3.5 h-3.5 text-slate-500" />
          Single scalar metric aggregated from dataset
        </p>
      </div>
    );
  }

  const xAxisKey = config.x_axis_key || Object.keys(data[0])[0];

  return (
    <div className="w-full space-y-2">
      <div className="flex items-center justify-between px-1">
        <h3 className="text-sm font-semibold text-slate-200">{config.title}</h3>
        <span className="text-[11px] font-mono text-slate-500 uppercase px-2 py-0.5 rounded bg-slate-800">
          {config.chart_type} chart
        </span>
      </div>

      {/* Explicit height wrapper preventing Recharts 0-height bug */}
      <div className="h-[360px] w-full rounded-xl bg-slate-950/60 border border-slate-800/80 p-4">
        <ResponsiveContainer width="100%" height="100%">
          {config.chart_type === "line" ? (
            <LineChart data={sanitizedData} margin={{ top: 10, right: 20, left: 0, bottom: 25 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
              <XAxis
                dataKey={xAxisKey}
                stroke="#94a3b8"
                fontSize={11}
                tickLine={false}
                dy={10}
              />
              <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} dx={-5} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0f172a",
                  borderColor: "#334155",
                  borderRadius: "0.5rem",
                  fontSize: "12px",
                  color: "#f8fafc",
                }}
              />
              <Legend wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }} />
              {config.y_axis_keys.map((key, idx) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={PALETTE[idx % PALETTE.length]}
                  strokeWidth={2.5}
                  dot={{ r: 4, strokeWidth: 1.5, fill: "#0f172a" }}
                  activeDot={{ r: 6, fill: PALETTE[idx % PALETTE.length] }}
                />
              ))}
            </LineChart>
          ) : config.chart_type === "area" ? (
            <AreaChart data={sanitizedData} margin={{ top: 10, right: 20, left: 0, bottom: 25 }}>
              <defs>
                {config.y_axis_keys.map((key, idx) => (
                  <linearGradient
                    key={key}
                    id={`areaGrad_${idx}`}
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop offset="5%" stopColor={PALETTE[idx % PALETTE.length]} stopOpacity={0.6} />
                    <stop offset="95%" stopColor={PALETTE[idx % PALETTE.length]} stopOpacity={0.0} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
              <XAxis dataKey={xAxisKey} stroke="#94a3b8" fontSize={11} tickLine={false} dy={10} />
              <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} dx={-5} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0f172a",
                  borderColor: "#334155",
                  borderRadius: "0.5rem",
                  fontSize: "12px",
                  color: "#f8fafc",
                }}
              />
              <Legend wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }} />
              {config.y_axis_keys.map((key, idx) => (
                <Area
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={PALETTE[idx % PALETTE.length]}
                  strokeWidth={2}
                  fill={`url(#areaGrad_${idx})`}
                />
              ))}
            </AreaChart>
          ) : config.chart_type === "pie" ? (
            <PieChart>
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0f172a",
                  borderColor: "#334155",
                  borderRadius: "0.5rem",
                  fontSize: "12px",
                  color: "#f8fafc",
                }}
              />
              <Legend wrapperStyle={{ fontSize: "12px" }} />
              <Pie
                data={sanitizedData}
                dataKey={config.y_axis_keys[0]}
                nameKey={xAxisKey}
                cx="50%"
                cy="50%"
                outerRadius={105}
                innerRadius={50}
                paddingAngle={3}
                label={({ name, percent }) =>
                  `${name}: ${(percent * 100).toFixed(0)}%`
                }
              >
                {sanitizedData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={PALETTE[index % PALETTE.length]} />
                ))}
              </Pie>
            </PieChart>
          ) : (
            /* Default: BarChart */
            <BarChart data={sanitizedData} margin={{ top: 10, right: 20, left: 0, bottom: 25 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
              <XAxis
                dataKey={xAxisKey}
                stroke="#94a3b8"
                fontSize={11}
                tickLine={false}
                dy={10}
              />
              <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} dx={-5} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0f172a",
                  borderColor: "#334155",
                  borderRadius: "0.5rem",
                  fontSize: "12px",
                  color: "#f8fafc",
                }}
              />
              <Legend wrapperStyle={{ fontSize: "12px", paddingTop: "10px" }} />
              {config.y_axis_keys.map((key, idx) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={PALETTE[idx % PALETTE.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
