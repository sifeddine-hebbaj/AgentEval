const COLORS: Record<string, string> = {
  ok: "text-pass border-pass/30 bg-pass/10",
  completed: "text-pass border-pass/30 bg-pass/10",
  error: "text-fail border-fail/30 bg-fail/10",
  failed: "text-fail border-fail/30 bg-fail/10",
  partial: "text-warn border-warn/30 bg-warn/10",
  pending: "text-muted border-border bg-white/5",
  running: "text-accent border-accent/30 bg-accent/10",
};

export default function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status] || COLORS.pending;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono border ${cls}`}>
      {status}
    </span>
  );
}
