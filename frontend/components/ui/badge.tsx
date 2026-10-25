export function Badge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    PAID: "bg-emerald-50 text-emerald-700",
    SENT: "bg-emerald-50 text-emerald-700",
    DUE: "bg-blue-50 text-blue-700",
    OVERDUE: "bg-red-50 text-red-700",
    PENDING: "bg-amber-50 text-amber-700",
    DRAFTED: "bg-purple-50 text-purple-700",
    APPROVED: "bg-blue-50 text-blue-700",
    FAILED: "bg-red-50 text-red-700",
    SEND_UNCERTAIN: "bg-amber-50 text-amber-800",
  };
  return (
    <span
      className={`inline-flex rounded px-2.5 py-1 text-[11px] font-semibold ${colors[status] || "bg-slate-100 text-slate-600"}`}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}
