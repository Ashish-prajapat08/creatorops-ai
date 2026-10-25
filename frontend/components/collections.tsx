"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  FileCheck2,
  RefreshCw,
  Send,
  Sparkles,
} from "lucide-react";
import { api, allRecords } from "@/lib/api";
import type { Brand, Invoice, Task } from "@/lib/types";
import { money } from "@/lib/utils";
import { ErrorNotice, Loading, useWorkspace } from "./workspace";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";

export function Collections() {
  const { agency } = useWorkspace();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [offset, setOffset] = useState(0);
  async function load(initial = false) {
    try {
      const [tasks, invoices, brands] = await Promise.all([
        api<Task[]>(`/collections/tasks?offset=${offset}`, {
          agency: agency.id,
        }),
        allRecords<Invoice>("/invoices", agency.id),
        allRecords<Brand>("/brands", agency.id),
      ]);
      setTasks(tasks.data);
      setInvoices(invoices.data);
      setBrands(brands.data);
      if (initial) setSelected(tasks.data[0]?.id || "");
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Could not load collections",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void Promise.resolve().then(() => load(true));
    const interval = setInterval(() => void load(), 2500);
    return () => clearInterval(interval);
  }, [agency.id, offset]); // eslint-disable-line react-hooks/exhaustive-deps
  const task = tasks.find((t) => t.id === selected);
  const canDraft = ["OWNER", "ADMIN", "FINANCE", "OPS"].includes(agency.role);
  return (
    <>
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-purple-700">
            AI-assisted collections
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">
            Collections desk
          </h1>
          <p className="mt-2 text-sm text-slate-500">
            Understand the context. Review the draft. Stay in control.
          </p>
        </div>
        {canDraft && (
          <Button
            variant="outline"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await api("/collections/scan", {
                  agency: agency.id,
                  method: "POST",
                });
                await load(true);
              } catch (error) {
                setError(
                  error instanceof Error ? error.message : "Scan failed",
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            <RefreshCw size={15} />
            Scan overdue invoices
          </Button>
        )}
      </div>
      {error && (
        <div className="mb-5">
          <ErrorNotice message={error} />
        </div>
      )}
      {loading ? (
        <Loading label="Loading collection tasks…" />
      ) : !tasks.length ? (
        <div className="rounded-xl border bg-white p-14 text-center">
          <FileCheck2 className="mx-auto mb-4 text-teal-700" />
          <h2 className="font-semibold">No collections to review</h2>
          <p className="mt-2 text-sm text-slate-500">
            The scheduled scan creates tasks for overdue issued invoices. You
            can run a scan now.
          </p>
        </div>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[300px_1fr]">
          <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
            <div className="border-b p-4 text-xs font-semibold uppercase tracking-widest text-slate-500">
              Collection queue
            </div>
            {tasks.map((t) => {
              const invoice = invoices.find((i) => i.id === t.invoice_id);
              return (
                <button
                  key={t.id}
                  className={`block w-full border-b p-5 text-left hover:bg-slate-50 ${selected === t.id ? "border-l-4 border-l-teal-700 bg-teal-50/50" : ""}`}
                  onClick={() => setSelected(t.id)}
                >
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">
                      {invoice?.invoice_number || "Invoice"}
                    </span>
                    <Badge status={t.status} />
                  </div>
                  <p className="mb-2 text-[10px] font-semibold text-slate-500">
                    {t.task_type.replaceAll("_", " ")}
                  </p>
                  <p className="text-xs text-slate-500">
                    {brands.find((b) => b.id === invoice?.brand_id)?.name ||
                      "Brand"}
                  </p>
                  {invoice && (
                    <p className="mt-2 text-sm font-medium">
                      {money(invoice.amount, invoice.currency)}
                    </p>
                  )}
                </button>
              );
            })}
            <div className="flex justify-between p-2">
              <Button
                variant="ghost"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                Previous
              </Button>
              <Button
                variant="ghost"
                disabled={tasks.length < 50}
                onClick={() => setOffset(offset + 50)}
              >
                Next
              </Button>
            </div>
          </section>
          {task && (
            <TaskReview
              key={`${task.id}-${task.draft_revision}`}
              task={task}
              invoice={invoices.find((i) => i.id === task.invoice_id)}
              reload={() => load()}
            />
          )}
        </div>
      )}
    </>
  );
}

function TaskReview({
  task,
  invoice,
  reload,
}: {
  task: Task;
  invoice?: Invoice;
  reload: () => Promise<void>;
}) {
  const { agency } = useWorkspace();
  const [subject, setSubject] = useState(task.draft_subject || "");
  const [body, setBody] = useState(task.draft_body || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const canDraft = ["OWNER", "ADMIN", "FINANCE", "OPS"].includes(agency.role);
  const canApprove = ["OWNER", "ADMIN", "FINANCE"].includes(agency.role);
  const dirty = subject !== task.draft_subject || body !== task.draft_body;
  async function action(name: string, payload?: unknown, method = "POST") {
    setBusy(true);
    setError("");
    try {
      await api(`/collections/tasks/${task.id}/${name}`, {
        agency: agency.id,
        method,
        body: payload,
      });
      await reload();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="border-b p-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Payment follow-up</h2>
          <Badge status={task.status} />
        </div>
        <div className="flex flex-wrap gap-6 text-xs text-slate-500">
          <Link
            href={`/invoices/${task.invoice_id}`}
            className="font-medium text-teal-800"
          >
            {invoice?.invoice_number || "View invoice"}{" "}
            <ArrowRight className="inline" size={12} />
          </Link>
          {invoice && (
            <>
              <span>{money(invoice.amount, invoice.currency)}</span>
              <span>Due {invoice.due_date}</span>
            </>
          )}
        </div>
      </div>
      <div className="p-6">
        <div className="mb-6 rounded-lg border border-purple-100 bg-purple-50/60 p-4">
          <p className="mb-2 flex items-center gap-2 text-xs font-semibold text-purple-900">
            <Sparkles size={14} />
            Recommended action
          </p>
          <p className="text-sm text-purple-900">{task.recommended_action}</p>
          <p className="mt-2 text-xs text-purple-700">
            {task.workflow_key === "DUE_SOON"
              ? "The payment due date is approaching. Review a courteous reminder before sending."
              : task.workflow_key.startsWith("PROMISE_MISSED:")
                ? "A reviewed payment promise has passed and an outstanding balance remains."
                : "This invoice is overdue and an outstanding balance remains."}
          </p>
        </div>
        {task.context_summary && (
          <details open className="mb-6 rounded-lg border border-slate-200 p-4">
            <summary className="cursor-pointer text-sm font-semibold">
              Collection context · {task.context_summary.message_count} relevant
              messages
            </summary>
            <div className="mt-3 space-y-2 text-sm text-slate-600">
              <p>
                <span className="font-medium">Intent:</span>{" "}
                {task.context_summary.intent.replaceAll("_", " ")}
              </p>
              <p>{task.context_summary.reason}</p>
              {task.context_summary.evidence && (
                <blockquote className="border-l-2 border-slate-300 pl-3 text-slate-500">
                  “{task.context_summary.evidence}”
                </blockquote>
              )}
              <p className="text-xs text-slate-400">
                Source: {task.context_summary.source}. Email claims do not
                change invoice status.
              </p>
            </div>
          </details>
        )}
        {error && (
          <div className="mb-4">
            <ErrorNotice message={error} />
          </div>
        )}
        {task.error_code && (
          <div className="mb-4">
            <ErrorNotice
              message={`Workflow needs attention: ${task.error_code}. ${task.status === "SEND_UNCERTAIN" ? "Check Gmail and reconcile this send. An uncertain send will never be automatically resent." : "Resolve the configuration or integration issue, then generate a new draft."}`}
            />
          </div>
        )}
        {task.status === "DRAFTING" && (
          <p
            role="status"
            className="rounded-lg bg-slate-50 p-6 text-sm text-slate-600"
          >
            Reviewing recent email context and drafting a payment follow-up…
          </p>
        )}
        {task.draft_body && (
          <div className="grid gap-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold">Email for review</h3>
              <span className="text-xs text-slate-400">
                Revision {task.draft_revision}
              </span>
            </div>
            <p className="rounded-md bg-slate-50 px-3 py-2 text-sm">
              <span className="text-slate-500">To:</span> {task.recipient}
            </p>
            <label>
              Subject
              <input
                aria-label="Subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                disabled={task.status !== "DRAFTED" || !canDraft}
                maxLength={250}
              />
            </label>
            <label>
              Body
              <textarea
                aria-label="Body"
                rows={12}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                disabled={task.status !== "DRAFTED" || !canDraft}
                maxLength={10000}
              />
            </label>
          </div>
        )}
        {task.status === "SENT" && (
          <div
            role="status"
            className="mt-6 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"
          >
            Email sent through Gmail.
            <p className="mt-2 break-all text-xs">
              Message ID: {task.gmail_message_id}
            </p>
            <Link
              href={`/invoices/${task.invoice_id}`}
              className="mt-3 inline-block font-medium underline"
            >
              View the complete audit trail
            </Link>
          </div>
        )}
        {task.status === "APPROVED" || task.status === "SENDING" ? (
          <p
            role="status"
            className="mt-5 rounded-md bg-blue-50 p-4 text-sm text-blue-800"
          >
            Approved email queued for Gmail. The worker will record the delivery
            result here.
          </p>
        ) : null}
        <div className="mt-6 flex flex-wrap items-center justify-end gap-3 border-t border-slate-100 pt-5">
          {canDraft &&
            ["PENDING", "FAILED", "REJECTED", "DRAFTED"].includes(
              task.status,
            ) && (
              <Button
                variant="outline"
                disabled={busy || (dirty && task.status === "DRAFTED")}
                onClick={() => void action("draft")}
              >
                <Sparkles size={15} />
                {task.status === "DRAFTED" ? "Regenerate" : "Generate draft"}
              </Button>
            )}
          {canDraft && task.status === "DRAFTED" && (
            <>
              <Button
                variant="destructive"
                disabled={busy}
                onClick={() => void action("reject")}
              >
                Reject
              </Button>
              {dirty && (
                <Button
                  variant="outline"
                  disabled={busy || !subject.trim() || !body.trim()}
                  onClick={() =>
                    void action(
                      "draft",
                      { subject, body, revision: task.draft_revision },
                      "PATCH",
                    )
                  }
                >
                  Save edits
                </Button>
              )}
            </>
          )}
          {canApprove && task.status === "DRAFTED" && (
            <Button
              disabled={busy || dirty}
              onClick={() =>
                void action("approve", { revision: task.draft_revision })
              }
            >
              <Send size={14} />
              Approve &amp; send
            </Button>
          )}
          {canApprove && task.status === "SEND_UNCERTAIN" && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void action("reconcile")}
            >
              Reconcile with Gmail
            </Button>
          )}
        </div>
        {task.status === "DRAFTED" && (
          <p className="mt-3 text-right text-xs text-slate-400">
            Approval sends this exact saved email to {task.recipient} through
            the agency’s connected Gmail.
          </p>
        )}
      </div>
    </section>
  );
}
