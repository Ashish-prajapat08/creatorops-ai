"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Audit } from "@/lib/types";
import { ErrorNotice, Loading, useWorkspace } from "./workspace";
import { Button } from "./ui/button";
import { money } from "@/lib/utils";

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function EventDetails({ details }: { details: Record<string, unknown> }) {
  const before = object(details.before);
  const after = object(details.after);
  return (
    <div className="mt-3 space-y-2 text-xs text-slate-500">
      {typeof after.invoice_number === "string" && (
        <p>
          {after.invoice_number}
          {typeof after.amount === "string" &&
          typeof after.currency === "string"
            ? ` · ${money(after.amount, after.currency)}`
            : ""}
          {typeof after.due_date === "string" ? ` · Due ${after.due_date}` : ""}
        </p>
      )}
      {Object.keys(before).length > 0 &&
        ["amount", "due_date", "status", "currency"]
          .filter((key) => before[key] !== after[key])
          .map((key) => (
            <p key={key}>
              <span className="capitalize">{key.replaceAll("_", " ")}</span>:{" "}
              {String(before[key])} → {String(after[key])}
            </p>
          ))}
      {typeof details.revision === "number" && (
        <p>Revision {details.revision}</p>
      )}
      {typeof details.recipient === "string" && <p>To: {details.recipient}</p>}
      {typeof details.status === "string" && (
        <p>Status: {details.status.toLowerCase().replaceAll("_", " ")}</p>
      )}
      {typeof details.role === "string" && (
        <p>Role: {details.role.toLowerCase()}</p>
      )}
      {typeof details.code === "string" && (
        <p>{details.code.toLowerCase().replaceAll("_", " ")}</p>
      )}
      {typeof details.body === "string" && (
        <details className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <summary className="cursor-pointer font-medium text-teal-800">
            View saved email
          </summary>
          {typeof details.subject === "string" && (
            <p className="mb-3 mt-3 font-medium text-slate-700">
              {details.subject}
            </p>
          )}
          <p className="whitespace-pre-wrap leading-relaxed">{details.body}</p>
        </details>
      )}
    </div>
  );
}

export function AuditList({
  logs,
  timezone,
}: {
  logs: Audit[];
  timezone: string;
}) {
  return (
    <div>
      {logs.map((log) => (
        <div key={log.id} className="flex gap-4 border-b border-slate-100 p-5">
          <span
            className={`mt-1 h-2 w-2 shrink-0 rounded-full ${log.actor_type === "AI" ? "bg-purple-500" : "bg-teal-600"}`}
          />
          <div className="min-w-0">
            <p className="text-sm font-medium">
              {log.action.toLowerCase().replaceAll("_", " ")}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {new Intl.DateTimeFormat("en", {
                dateStyle: "medium",
                timeStyle: "short",
                timeZone: timezone,
              }).format(new Date(log.created_at))}{" "}
              · {log.actor_type}
            </p>
            <EventDetails details={log.details} />
          </div>
        </div>
      ))}
      {!logs.length && (
        <p className="p-10 text-center text-sm text-slate-500">
          No audit events yet.
        </p>
      )}
    </div>
  );
}
export function AuditPage() {
  const { agency } = useWorkspace();
  const [logs, setLogs] = useState<Audit[]>();
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    api<Audit[]>(`/audit?offset=${offset}`, { agency: agency.id })
      .then((result) => setLogs(result.data))
      .catch((e) => setError(e.message));
  }, [agency.id, offset]);
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight">Audit trail</h1>
      <p className="mb-7 mt-2 text-sm text-slate-500">
        Every financial change, AI draft, human decision, and send result.
      </p>
      {error && <ErrorNotice message={error} />}
      <section className="rounded-xl border bg-white">
        {!logs ? (
          <Loading label="Loading audit events…" />
        ) : (
          <>
            <AuditList logs={logs} timezone={agency.timezone} />
            <div className="flex justify-between p-4">
              <Button
                variant="ghost"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                Previous
              </Button>
              <Button
                variant="ghost"
                disabled={logs.length < 50}
                onClick={() => setOffset(offset + 50)}
              >
                Next
              </Button>
            </div>
          </>
        )}
      </section>
    </>
  );
}
