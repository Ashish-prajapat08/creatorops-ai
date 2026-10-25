"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, allRecords } from "@/lib/api";
import type { EmailAnalysis, Invoice } from "@/lib/types";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { ErrorNotice, Loading, useWorkspace } from "./workspace";

const classifications = [
  "PAYMENT_PROMISED",
  "PAYMENT_SENT",
  "DISPUTE",
  "PO_REQUIRED",
  "INFORMATION_REQUESTED",
  "PAYMENT_DELAYED",
  "OTHER",
  "UNCERTAIN",
];
export function EmailIntelligencePage() {
  const { agency } = useWorkspace();
  const [rows, setRows] = useState<EmailAnalysis[]>();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [selected, setSelected] = useState("");
  const [syncInvoice, setSyncInvoice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const canReview = ["OWNER", "ADMIN", "FINANCE", "OPS"].includes(agency.role);
  useEffect(() => {
    let active = true;
    allRecords<Invoice>("/invoices", agency.id)
      .then((r) => {
        if (active) setInvoices(r.data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [agency.id]);
  async function load() {
    const response = await api<EmailAnalysis[]>(
      `/email-intelligence?offset=${offset}${filter ? `&status=${filter}` : ""}`,
      { agency: agency.id },
    );
    setRows(response.data);
  }
  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const r = await api<EmailAnalysis[]>(
          `/email-intelligence?offset=${offset}${filter ? `&status=${filter}` : ""}`,
          { agency: agency.id },
        );
        if (active) setRows(r.data);
      } catch (e) {
        if (active)
          setError(e instanceof Error ? e.message : "Could not load replies");
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [agency.id, offset, filter]);
  const row = rows?.find((r) => r.id === selected) || rows?.[0];
  return (
    <>
      <h1 className="text-3xl font-semibold">Email intelligence</h1>
      <p className="mb-6 mt-2 text-sm text-slate-500">
        Review relevant inbound replies and source-linked payment promises.
        Email claims never confirm receipt of money.
      </p>
      {canReview && (
        <form
          className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border bg-white p-5"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api(`/invoices/${syncInvoice}/sync-email`, {
                agency: agency.id,
                method: "POST",
              });
              setNotice(
                "Email synchronization queued. New replies will be classified in the background.",
              );
            } catch (e) {
              setError(e instanceof Error ? e.message : "Sync failed");
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="min-w-60 flex-1">
            Invoice to synchronize
            <select
              aria-label="Invoice to synchronize"
              required
              value={syncInvoice}
              onChange={(e) => setSyncInvoice(e.target.value)}
            >
              <option value="">Select invoice</option>
              {invoices.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.invoice_number}
                </option>
              ))}
            </select>
          </label>
          <Button disabled={busy || !syncInvoice}>Sync email</Button>
        </form>
      )}
      {notice && (
        <p
          role="status"
          className="mb-4 rounded-md bg-teal-50 p-4 text-sm text-teal-800"
        >
          {notice}
        </p>
      )}
      {error && (
        <div className="mb-4">
          <ErrorNotice message={error} />
        </div>
      )}
      <label className="mb-5 max-w-xs">
        Processing state
        <select
          aria-label="Processing state"
          value={filter}
          onChange={(e) => {
            setOffset(0);
            setFilter(e.target.value);
          }}
        >
          <option value="">All replies</option>
          {[
            "PENDING",
            "PROCESSING",
            "REVIEW",
            "ACCEPTED",
            "REJECTED",
            "FAILED",
          ].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      {!rows ? (
        <Loading label="Loading email intelligence…" />
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[300px_1fr]">
          <section className="overflow-hidden rounded-xl border bg-white">
            {rows.map((item) => (
              <button
                key={item.id}
                onClick={() => setSelected(item.id)}
                className={`block w-full border-b p-5 text-left ${row?.id === item.id ? "bg-teal-50" : "hover:bg-slate-50"}`}
              >
                <p className="mb-2 text-sm font-semibold">
                  {invoices.find((i) => i.id === item.invoice_id)
                    ?.invoice_number || "Invoice reply"}
                </p>
                <p className="mb-3 truncate text-xs text-slate-500">
                  {item.source.subject}
                </p>
                <Badge status={item.status} />
                <p className="mt-2 text-xs text-slate-500">
                  {item.classification?.replaceAll("_", " ") ||
                    "Awaiting processing"}
                </p>
              </button>
            ))}
            {!rows.length && (
              <p className="p-8 text-sm text-slate-500">
                No relevant replies yet. Connect Gmail, then synchronize an
                invoice.
              </p>
            )}
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
                disabled={rows.length < 50}
                onClick={() => setOffset(offset + 50)}
              >
                Next
              </Button>
            </div>
          </section>
          {row && (
            <EmailReview
              key={`${row.id}-${row.revision}`}
              row={row}
              canReview={canReview}
              reload={load}
            />
          )}
        </div>
      )}
    </>
  );
}

function EmailReview({
  row,
  canReview,
  reload,
}: {
  row: EmailAnalysis;
  canReview: boolean;
  reload: () => Promise<void>;
}) {
  const { agency } = useWorkspace();
  const output = row.review_decision?.effective_output || row.model_output;
  const [classification, setClassification] = useState(
    output?.classification || "UNCERTAIN",
  );
  const [day, setDay] = useState(output?.promised_date || "");
  const [dateStatus, setDateStatus] = useState(
    output?.date_status === "AMBIGUOUS" ? "AMBIGUOUS" : "MISSING",
  );
  const [reason, setReason] = useState(row.review_decision?.reason || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function review(decision: "ACCEPT" | "REJECT") {
    setBusy(true);
    setError("");
    try {
      await api(`/email-intelligence/${row.id}/review`, {
        agency: agency.id,
        method: "POST",
        body: {
          revision: row.revision,
          decision,
          classification,
          promised_date:
            classification === "PAYMENT_PROMISED" && day ? day : null,
          date_status:
            classification === "PAYMENT_PROMISED"
              ? day
                ? "EXPLICIT"
                : dateStatus
              : "NOT_APPLICABLE",
          reason,
        },
      });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="rounded-xl border bg-white p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Inbound reply review</h2>
        <Badge status={row.status} />
      </div>
      <Link
        className="text-sm text-teal-800"
        href={`/invoices/${row.invoice_id}`}
      >
        View invoice, promises, and financial history →
      </Link>
      <p className="mb-4 mt-3 text-xs text-slate-500">
        {row.source.sender_email} · {row.source.sent_at}
      </p>
      <blockquote className="mb-6 whitespace-pre-wrap rounded-md border bg-slate-50 p-4 text-sm">
        {row.source.body_text}
      </blockquote>
      {row.error_code && (
        <ErrorNotice
          message={`Processing failed: ${row.error_code}. Fix configuration or review the source, then reprocess.`}
        />
      )}
      {error && <ErrorNotice message={error} />}
      {row.review_decision && (
        <div
          role="status"
          className="mb-5 rounded-md border border-teal-200 bg-teal-50 p-4 text-sm text-teal-900"
        >
          <p className="font-semibold">Human review saved</p>
          <p className="mt-1">
            Decision:{" "}
            {row.review_decision.decision === "ACCEPT"
              ? "Accepted"
              : "Rejected"}
          </p>
          <p className="mt-1 whitespace-pre-wrap">
            Review reason: {row.review_decision.reason}
          </p>
          <p className="mt-2 text-xs">
            This records the sender’s claim. It does not confirm payment or send
            an email.
          </p>
        </div>
      )}
      {output && (
        <>
          <div className="mb-5 rounded-md bg-purple-50 p-4 text-sm">
            <p className="font-semibold">
              {output.classification.replaceAll("_", " ")} ·{" "}
              {Math.round(output.confidence * 100)}% confidence
            </p>
            <p className="mt-2">{output.summary}</p>
            <p className="mt-2 text-purple-800">{output.recommended_action}</p>
            {row.review_reasons.length > 0 && (
              <p className="mt-3 text-xs text-amber-800">
                Review required:{" "}
                {row.review_reasons
                  .map((r) => r.toLowerCase().replaceAll("_", " "))
                  .join(", ")}
              </p>
            )}
          </div>
          <dl className="mb-5 grid gap-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-slate-500">Promised date</dt>
              <dd>
                {output.promised_date || "Not explicit"} ·{" "}
                {output.date_status.toLowerCase()}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Sender payment claim</dt>
              <dd>
                {output.payment_amount
                  ? `${output.currency || "Currency unspecified"} ${output.payment_amount}`
                  : "Amount not extracted"}
              </dd>
            </div>
            {output.payment_reference && (
              <div>
                <dt className="text-xs text-slate-500">Payment reference</dt>
                <dd>{output.payment_reference}</dd>
              </div>
            )}
            {output.delay_reason && (
              <div>
                <dt className="text-xs text-slate-500">Delay reason</dt>
                <dd>{output.delay_reason}</dd>
              </div>
            )}
          </dl>
          <details className="mb-5">
            <summary className="cursor-pointer text-sm font-medium">
              Source evidence
            </summary>
            {output.evidence.map((e, index) => (
              <p
                key={index}
                className="mt-2 border-l-2 pl-3 text-sm text-slate-500"
              >
                {e.field.replaceAll("_", " ")}: “{e.quote}”
              </p>
            ))}
          </details>
        </>
      )}
      {canReview &&
        output &&
        ["REVIEW", "ACCEPTED", "REJECTED"].includes(row.status) && (
          <div className="grid gap-4 border-t pt-5">
            <label>
              Reviewed classification
              <select
                aria-label="Reviewed classification"
                value={classification}
                onChange={(e) => setClassification(e.target.value)}
              >
                {classifications.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            {classification === "PAYMENT_PROMISED" && (
              <>
                <label>
                  Reviewed payment date
                  <input
                    aria-label="Reviewed payment date"
                    type="date"
                    value={day}
                    onChange={(e) => setDay(e.target.value)}
                  />
                </label>
                {!day && (
                  <label>
                    Date uncertainty
                    <select
                      aria-label="Date uncertainty"
                      value={dateStatus}
                      onChange={(e) => setDateStatus(e.target.value)}
                    >
                      <option value="MISSING">Missing</option>
                      <option value="AMBIGUOUS">Ambiguous</option>
                    </select>
                  </label>
                )}
              </>
            )}
            <label>
              Review reason
              <textarea
                aria-label="Review reason"
                required
                minLength={3}
                maxLength={1000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <div className="flex justify-end gap-3">
              <Button
                variant="destructive"
                disabled={busy || reason.trim().length < 3}
                onClick={() => void review("REJECT")}
              >
                Reject interpretation
              </Button>
              <Button
                disabled={busy || reason.trim().length < 3}
                onClick={() => void review("ACCEPT")}
              >
                Accept reviewed claim
              </Button>
            </div>
            <p className="text-xs text-slate-500">
              Accepting records an interpretation of the sender’s claim. It does
              not verify a payment or send an email.
            </p>
          </div>
        )}
      {canReview && !["PENDING", "PROCESSING"].includes(row.status) && (
        <Button
          className="mt-5"
          variant="outline"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api(`/email-intelligence/${row.id}/reprocess`, {
                agency: agency.id,
                method: "POST",
              });
              await reload();
            } catch (e) {
              setError(e instanceof Error ? e.message : "Reprocess failed");
            } finally {
              setBusy(false);
            }
          }}
        >
          Reprocess source email
        </Button>
      )}
    </section>
  );
}
