import type { ReactNode } from "react";
import type { Status } from "../api";
import { pretty } from "../api";

const STATUS_STYLE: Record<Status, string> = {
  QUEUED: "bg-stone-100 text-stone-500 border-stone-200",
  RECEIVED: "bg-blue-50 text-live border-blue-200",
  INSPECTING: "bg-blue-50 text-live border-blue-200",
  PRICING: "bg-blue-50 text-live border-blue-200",
  DECIDING: "bg-blue-50 text-live border-blue-200",
  EXECUTING: "bg-blue-50 text-live border-blue-200",
  ESCALATED: "bg-orange-50 text-hold border-orange-300",
  CLOSED: "bg-green-50 text-go border-green-200",
  FAILED: "bg-red-50 text-fraud border-red-200",
  ERROR: "bg-red-50 text-fraud border-red-200",
};
const LIVE: Status[] = ["RECEIVED", "INSPECTING", "PRICING", "DECIDING", "EXECUTING"];

export function StatusChip({ status }: { status: Status }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium tracking-wider ${STATUS_STYLE[status]}`}>
      {LIVE.includes(status) && <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-current" />}
      {status}
    </span>
  );
}

export const ACTION_STYLE: Record<string, string> = {
  RESTOCK: "bg-green-700 text-white",
  REFURBISH: "bg-indigo-700 text-white",
  RETURN_TO_VENDOR: "bg-violet-700 text-white",
  LIQUIDATE: "bg-stone-600 text-white",
  ESCALATE: "bg-hold text-white",
};

export function ActionBadge({ action, size = "sm" }: { action?: string | null; size?: "sm" | "lg" }) {
  if (!action) return null;
  const cls = size === "lg" ? "px-3 py-1 text-sm" : "px-1.5 py-0.5 text-[10px]";
  return <span className={`rounded font-mono font-semibold tracking-wide ${cls} ${ACTION_STYLE[action] ?? "bg-stone-500 text-white"}`}>{pretty(action).toUpperCase()}</span>;
}

export function Card({ title, tag, children, className = "" }: { title: string; tag?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-4 ${className}`}>
      <header className="mb-3 flex items-center justify-between gap-2">
        <h3 className="label">{title}</h3>
        {tag}
      </header>
      {children}
    </section>
  );
}

export function SponsorTag({ children, color }: { children: ReactNode; color: string }) {
  return <span className={`rounded-full px-2 py-0.5 font-mono text-[10px] font-medium ${color}`}>{children}</span>;
}

export function Meter({ value, max = 1, color = "bg-ink" }: { value: number; max?: number; color?: string }) {
  const pct = Math.max(0, Math.min(100, (100 * value) / (max || 1)));
  return (
    <div className="h-1.5 w-full rounded-full bg-stone-200">
      <div className={`h-1.5 rounded-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  );
}
