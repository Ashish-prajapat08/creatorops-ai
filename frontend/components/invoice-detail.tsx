"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type {
  Audit,
  Brand,
  Campaign,
  Creator,
  Invoice,
  Task,
  InvoiceBalance,
  PromiseRecord,
  Allocation,
} from "@/lib/types";
import { money } from "@/lib/utils";
import { ErrorNotice, Loading, useWorkspace } from "./workspace";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { AuditList } from "./audit";
type History = {
  invoice: Invoice;
  audit: Audit[];
  tasks: Task[];
  balance: InvoiceBalance;
  promises: PromiseRecord[];
  allocations: Allocation[];
  emails: {
    id: string;
    subject: string;
    body: string;
    sender: string;
    sent_at: string;
    direction: string;
  }[];
};
export function InvoiceDetail({ id }: { id: string }) {
  const { agency } = useWorkspace();
  const [history, setHistory] = useState<History>();
  const [brand, setBrand] = useState<Brand>();
  const [campaign, setCampaign] = useState<Campaign>();
  const [creator, setCreator] = useState<Creator>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const { data } = await api<History>(`/invoices/${id}/history`, {
          agency: agency.id,
        });
        const [b, c] = await Promise.all([
          api<Brand>(`/brands/${data.invoice.brand_id}`, { agency: agency.id }),
          api<Campaign>(`/campaigns/${data.invoice.campaign_id}`, {
            agency: agency.id,
          }),
        ]);
        const cr = await api<Creator>(`/creators/${c.data.creator_id}`, {
          agency: agency.id,
        });
        if (active) {
          setHistory(data);
          setBrand(b.data);
          setCampaign(c.data);
          setCreator(cr.data);
        }
      } catch (error) {
        if (active)
          setError(
            error instanceof Error ? error.message : "Could not load invoice",
          );
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [id, agency.id]);
  if (error) return <ErrorNotice message={error} />;
  if (!history)
    return <Loading label="Loading invoice and collection history…" />;
  const invoice = history.invoice;
  return (
    <>
      <Link href="/invoices" className="text-sm text-teal-800">
        ← Invoices
      </Link>
      <div className="mb-7 mt-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">{invoice.invoice_number}</h1>
          <p className="mt-2 text-slate-500">
            {brand?.name} · {campaign?.name}
          </p>
        </div>
        <Badge status={invoice.status} />
      </div>
      <section className="mb-6 rounded-xl border bg-white p-6">
        <p className="mb-6 text-3xl font-semibold">
          {money(invoice.amount, invoice.currency)}
        </p>
        <div className="mb-6 grid gap-4 rounded-lg bg-slate-50 p-4 sm:grid-cols-3">
          <div>
            <p className="text-xs text-slate-500">Recorded paid amount</p>
            <p className="mt-1 font-semibold">
              {money(history.balance.paid_amount, invoice.currency)}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Outstanding balance</p>
            <p className="mt-1 font-semibold text-teal-800">
              {money(history.balance.outstanding_balance, invoice.currency)}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Overpayment</p>
            <p className="mt-1 font-semibold">
              {money(history.balance.overpaid_amount, invoice.currency)}
            </p>
          </div>
        </div>
        {history.balance.legacy_manual_paid && (
          <p className="mb-5 text-xs text-slate-500">
            Legacy manually-paid status. No imported transaction evidence is
            implied.
          </p>
        )}
        <dl className="grid gap-5 sm:grid-cols-3">
          {[
            ["Brand", brand?.name],
            ["Campaign", campaign?.name],
            ["Creator", creator?.name],
            ["Contact", brand?.contact_email],
            ["Issue date", invoice.issue_date],
            ["Due date", invoice.due_date],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="mt-1 text-sm font-medium">{value}</dd>
            </div>
          ))}
        </dl>
        {invoice.description && (
          <p className="mt-6 border-t pt-4 text-sm text-slate-500">
            {invoice.description}
          </p>
        )}
      </section>
      <section className="mb-6 grid gap-6 rounded-xl border bg-white p-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-4 font-semibold">Payment promise history</h2>
          {!history.promises.length && (
            <p className="text-sm text-slate-500">
              No payment promises recorded.
            </p>
          )}
          {history.promises.map((p) => (
            <div key={p.id} className="mb-3 rounded-md border p-3 text-sm">
              <p className="mb-2">
                {p.promised_date || "Date needs review"} ·{" "}
                {p.date_status.toLowerCase()}
              </p>
              <Badge status={p.status} />
              <p className="mt-2 text-slate-500">“{p.evidence}”</p>
              <Link
                href="/email-intelligence"
                className="mt-2 inline-block text-xs text-teal-800"
              >
                Review source interpretation →
              </Link>
            </div>
          ))}
        </div>
        <div>
          <h2 className="mb-4 font-semibold">Payment allocations</h2>
          {!history.allocations.length && (
            <p className="text-sm text-slate-500">
              No confirmed manual payment allocations.
            </p>
          )}
          {history.allocations.map((a) => (
            <div key={a.id} className="mb-3 rounded-md border p-3 text-sm">
              <p className="mb-2">{money(a.amount, invoice.currency)}</p>
              <Badge status={a.status} />
              <p className="mt-2 text-xs text-slate-500">
                Confirmed {a.confirmed_at}
              </p>
              {a.reversal_reason && (
                <p className="mt-2 text-xs text-slate-500">
                  Correction: {a.reversal_reason}
                </p>
              )}
            </div>
          ))}
          <Link
            href="/reconciliation"
            className="mt-3 inline-block text-sm text-teal-800"
          >
            Open reconciliation center →
          </Link>
        </div>
      </section>
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <section className="rounded-xl border bg-white">
          <h2 className="border-b p-5 font-semibold">Collection history</h2>
          <AuditList logs={history.audit} timezone={agency.timezone} />
          <div className="p-5">
            <Button variant="outline" asChild>
              <Link href="/collections">Review collection tasks</Link>
            </Button>
          </div>
        </section>
        <section className="rounded-xl border bg-white">
          <h2 className="border-b p-5 font-semibold">Relevant email context</h2>
          {history.emails.map((email) => (
            <details key={email.id} className="border-b p-5">
              <summary className="cursor-pointer text-sm font-medium">
                {email.subject} · {email.direction.toLowerCase()}
              </summary>
              <p className="mt-3 text-xs text-slate-500">{email.sender}</p>
              <p className="mt-3 whitespace-pre-wrap text-sm text-slate-600">
                {email.body}
              </p>
            </details>
          ))}
          {!history.emails.length && (
            <p className="p-7 text-sm text-slate-500">
              Relevant Gmail messages appear when a collection draft is
              generated.
            </p>
          )}
        </section>
      </div>
    </>
  );
}
