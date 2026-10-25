"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, allRecords } from "@/lib/api";
import type {
  Brand,
  Invoice,
  PaymentTransaction,
  Reconciliation,
} from "@/lib/types";
import { money } from "@/lib/utils";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "./ui/dialog";
import { ErrorNotice, Loading, useWorkspace } from "./workspace";

export function ReconciliationPage() {
  const { agency } = useWorkspace();
  const [rows, setRows] = useState<PaymentTransaction[]>();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [selected, setSelected] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  async function load() {
    const [transactions, invoiceRows, brandRows] = await Promise.all([
      api<PaymentTransaction[]>(`/transactions?offset=${offset}`, {
        agency: agency.id,
      }),
      allRecords<Invoice>("/invoices", agency.id),
      allRecords<Brand>("/brands", agency.id),
    ]);
    setRows(transactions.data);
    setInvoices(invoiceRows.data);
    setBrands(brandRows.data);
  }
  useEffect(() => {
    void Promise.resolve()
      .then(load)
      .catch((e) => setError(e.message));
  }, [agency.id, offset]); // eslint-disable-line react-hooks/exhaustive-deps
  const chosen = rows?.find((t) => t.id === selected) || rows?.[0];
  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const values = Object.fromEntries(new FormData(e.currentTarget));
    const payload = { ...values };
    for (const key of [
      "brand_id",
      "invoice_id",
      "external_reference",
      "invoice_reference",
    ])
      if (!payload[key]) delete payload[key];
    try {
      const r = await api<PaymentTransaction>("/transactions", {
        agency: agency.id,
        method: "POST",
        body: payload,
      });
      setSelected(r.data.id);
      setOpen(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Reconciliation center</h1>
          <p className="mt-2 text-sm text-slate-500">
            Review manually entered payment records and confirm invoice
            allocations.
          </p>
        </div>
        {["OWNER", "ADMIN"].includes(agency.role) && (
          <Button onClick={() => setOpen(true)}>
            Enter manual transaction
          </Button>
        )}
      </div>
      <p className="mb-6 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        Manual and mock records are not verified bank transactions. This
        workspace does not process payments or transfer funds.
      </p>
      {error && (
        <div className="mb-4">
          <ErrorNotice message={error} />
        </div>
      )}
      {!rows ? (
        <Loading label="Loading manual transactions…" />
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[300px_1fr]">
          <section className="overflow-hidden rounded-xl border bg-white">
            {rows.map((tx) => (
              <button
                key={tx.id}
                className={`block w-full border-b p-5 text-left ${chosen?.id === tx.id ? "bg-teal-50" : "hover:bg-slate-50"}`}
                onClick={() => setSelected(tx.id)}
              >
                <p className="mb-2 truncate text-sm font-semibold">
                  {tx.external_id}
                </p>
                <p className="mb-3 text-sm">{money(tx.amount, tx.currency)}</p>
                <Badge status={tx.status} />
                <p className="mt-2 text-xs text-slate-500">
                  {tx.source} · {tx.transaction_date}
                </p>
              </button>
            ))}
            {!rows.length && (
              <p className="p-8 text-sm text-slate-500">
                No payment records entered yet. An owner or administrator can
                add a manual or mock record.
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
          {chosen && (
            <TransactionReview
              key={`${chosen.id}-${chosen.revision}`}
              id={chosen.id}
              invoices={invoices}
              refreshList={load}
            />
          )}
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle className="text-xl font-semibold">
            Enter manual transaction
          </DialogTitle>
          <DialogDescription className="my-3 text-sm text-slate-500">
            Record imported evidence for review. No money is collected or
            transferred.
          </DialogDescription>
          <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
            <label>
              Source transaction ID
              <input name="external_id" required maxLength={160} />
            </label>
            <label>
              Source
              <select aria-label="Source" name="source">
                <option>MANUAL</option>
                <option>MOCK</option>
              </select>
            </label>
            <label>
              Transaction amount
              <input
                name="amount"
                required
                inputMode="decimal"
                pattern="[0-9]+(\.[0-9]{1,2})?"
              />
            </label>
            <label>
              Transaction currency
              <input
                name="currency"
                required
                pattern="[A-Z]{3}"
                maxLength={3}
                defaultValue={agency.default_currency}
              />
            </label>
            <label>
              Transaction date
              <input name="transaction_date" type="date" required />
            </label>
            <label>
              External payment reference
              <input name="external_reference" maxLength={160} />
            </label>
            <label>
              Payer brand
              <select aria-label="Payer brand" name="brand_id">
                <option value="">Unspecified</option>
                {brands.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Known invoice
              <select aria-label="Known invoice" name="invoice_id">
                <option value="">Unknown — review matches</option>
                {invoices.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.invoice_number}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Invoice reference in payment
              <input name="invoice_reference" maxLength={80} />
            </label>
            <label>
              Description
              <textarea
                aria-label="Description"
                name="description"
                maxLength={5000}
              />
            </label>
            {error && (
              <div className="sm:col-span-2">
                <ErrorNotice message={error} />
              </div>
            )}
            <div className="flex justify-end gap-3 sm:col-span-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button disabled={busy}>Save manual transaction</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

function TransactionReview({
  id,
  invoices,
  refreshList,
}: {
  id: string;
  invoices: Invoice[];
  refreshList: () => Promise<void>;
}) {
  const { agency } = useWorkspace();
  const [data, setData] = useState<Reconciliation>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [acknowledge, setAcknowledge] = useState(false);
  const [allocations, setAllocations] = useState<
    { invoice_id: string; amount: string }[]
  >([{ invoice_id: "", amount: "" }]);
  const [reversing, setReversing] = useState("");
  useEffect(() => {
    let active = true;
    api<Reconciliation>(`/transactions/${id}/reconciliation`, {
      agency: agency.id,
    })
      .then((r) => {
        if (active) setData(r.data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [id, agency.id]);
  const canReview = ["OWNER", "ADMIN", "FINANCE"].includes(agency.role);
  async function action(kind: string, payload: unknown) {
    setBusy(true);
    setError("");
    try {
      const r = await api<Reconciliation>(
        kind.startsWith("/allocations/") ? kind : `/transactions/${id}/${kind}`,
        { agency: agency.id, method: "POST", body: payload },
      );
      setData(r.data);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }
  if (!data)
    return error ? (
      <ErrorNotice message={error} />
    ) : (
      <Loading label="Loading deterministic matches…" />
    );
  const tx = data.transaction;
  return (
    <section className="rounded-xl border bg-white p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">
          {money(tx.amount, tx.currency)}
        </h2>
        <Badge status={data.match_status} />
      </div>
      <dl className="mb-6 grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-slate-500">Source transaction</dt>
          <dd className="break-all">
            {tx.external_id} · {tx.source}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">External reference</dt>
          <dd>{tx.external_reference || "Not supplied"}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Confirmed allocations</dt>
          <dd>{money(data.allocated_amount, tx.currency)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Still unallocated</dt>
          <dd>{money(data.unallocated_amount, tx.currency)}</dd>
        </div>
      </dl>
      {tx.description && (
        <p className="mb-5 text-sm text-slate-500">{tx.description}</p>
      )}
      {error && (
        <div className="mb-4">
          <ErrorNotice message={error} />
        </div>
      )}
      <h3 className="mb-3 text-sm font-semibold">
        Deterministic invoice candidates
      </h3>
      {data.match_status === "AMBIGUOUS" && (
        <p className="mb-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          More than one invoice matches. Choose explicitly after checking the
          payment evidence.
        </p>
      )}
      {!data.candidates.length && (
        <p className="mb-5 text-sm text-slate-500">
          No identifier or payer-based match. Equal amounts alone never create a
          match.
        </p>
      )}
      {data.candidates.map((c) => (
        <div key={c.invoice_id} className="mb-3 rounded-md border p-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <Link
              className="text-sm font-semibold text-teal-800"
              href={`/invoices/${c.invoice_id}`}
            >
              {c.invoice_number}
            </Link>
            {canReview && (
              <Button
                variant="outline"
                disabled={busy || tx.status === "REJECTED"}
                onClick={() =>
                  setAllocations([
                    {
                      invoice_id: c.invoice_id,
                      amount: data.unallocated_amount,
                    },
                  ])
                }
              >
                Select invoice
              </Button>
            )}
          </div>
          <p className="text-xs text-slate-500">
            {c.match_type.replaceAll("_", " ")} · Outstanding{" "}
            {money(c.outstanding_balance, c.currency)} · Difference{" "}
            {money(c.amount_difference, tx.currency)}
          </p>
          {c.warnings.length > 0 && (
            <p className="mt-2 text-xs text-amber-800">
              {c.warnings
                .map((w) => w.toLowerCase().replaceAll("_", " "))
                .join(", ")}
            </p>
          )}
        </div>
      ))}
      {canReview &&
        tx.status !== "REJECTED" &&
        data.unallocated_amount !== "0.00" && (
          <form
            className="mt-6 grid gap-4 border-t pt-5"
            onSubmit={(e) => {
              e.preventDefault();
              void action("approve", {
                idempotency_key: crypto.randomUUID(),
                revision: tx.revision,
                allocations,
                acknowledge_warnings: acknowledge,
                reason,
              });
            }}
          >
            <h3 className="text-sm font-semibold">Reviewed allocation</h3>
            {allocations.map((allocation, index) => (
              <div
                key={index}
                className="grid items-end gap-3 sm:grid-cols-[1fr_150px_auto]"
              >
                <label>
                  Allocation invoice
                  <select
                    aria-label={`Allocation invoice ${index + 1}`}
                    required
                    value={allocation.invoice_id}
                    onChange={(e) =>
                      setAllocations(
                        allocations.map((a, i) =>
                          i === index
                            ? { ...a, invoice_id: e.target.value }
                            : a,
                        ),
                      )
                    }
                  >
                    <option value="">Choose invoice</option>
                    {invoices.map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.invoice_number} · {i.currency}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Allocation amount
                  <input
                    aria-label={`Allocation amount ${index + 1}`}
                    required
                    inputMode="decimal"
                    pattern="[0-9]+(\.[0-9]{1,2})?"
                    value={allocation.amount}
                    onChange={(e) =>
                      setAllocations(
                        allocations.map((a, i) =>
                          i === index ? { ...a, amount: e.target.value } : a,
                        ),
                      )
                    }
                  />
                </label>
                {allocations.length > 1 && (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() =>
                      setAllocations(allocations.filter((_, i) => i !== index))
                    }
                  >
                    Remove
                  </Button>
                )}
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              disabled={allocations.length >= 20}
              onClick={() =>
                setAllocations([...allocations, { invoice_id: "", amount: "" }])
              }
            >
              Add invoice allocation
            </Button>
            <label>
              Decision reason
              <textarea
                aria-label="Decision reason"
                required
                minLength={3}
                maxLength={1000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <label className="flex items-start gap-3 font-normal">
              <input
                type="checkbox"
                className="mt-1 w-auto"
                checked={acknowledge}
                onChange={(e) => setAcknowledge(e.target.checked)}
              />
              I reviewed discrepancies, possible duplicates, overpayments, and
              any split across invoices.
            </label>
            <div className="flex flex-wrap justify-end gap-3">
              <Button
                type="button"
                variant="destructive"
                disabled={busy || reason.trim().length < 3}
                onClick={() =>
                  void action("reject", {
                    idempotency_key: crypto.randomUUID(),
                    revision: tx.revision,
                    reason,
                  })
                }
              >
                Reject transaction
              </Button>
              <Button disabled={busy || reason.trim().length < 3}>
                Confirm allocation
              </Button>
            </div>
            <p className="text-xs text-slate-500">
              Confirmation updates the invoice balance from this manual record.
              It does not verify a bank deposit or execute a payment.
            </p>
          </form>
        )}
      <h3 className="mb-3 mt-7 border-t pt-5 text-sm font-semibold">
        Allocation history
      </h3>
      {data.allocations.length === 0 && (
        <p className="text-sm text-slate-500">No confirmed allocations.</p>
      )}
      {data.allocations.map((a) => (
        <div key={a.id} className="mb-3 rounded-md border p-4 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Link href={`/invoices/${a.invoice_id}`} className="text-teal-800">
              {invoices.find((i) => i.id === a.invoice_id)?.invoice_number ||
                "Invoice"}{" "}
              · {money(a.amount, tx.currency)}
            </Link>
            <Badge status={a.status} />
            {canReview && a.status === "CONFIRMED" && (
              <Button variant="outline" onClick={() => setReversing(a.id)}>
                Reverse allocation
              </Button>
            )}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Confirmed {a.confirmed_at}
          </p>
          {a.reversal_reason && (
            <p className="mt-2 text-xs text-slate-500">
              Correction: {a.reversal_reason}
            </p>
          )}
          {reversing === a.id && (
            <form
              className="mt-4 grid gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                const form = new FormData(e.currentTarget);
                void action(`/allocations/${a.id}/reverse`, {
                  reason: String(form.get("reason")),
                });
              }}
            >
              <label>
                Reversal reason
                <textarea
                  aria-label="Reversal reason"
                  name="reason"
                  required
                  minLength={3}
                  maxLength={1000}
                />
              </label>
              <Button variant="destructive" disabled={busy}>
                Confirm reversal
              </Button>
            </form>
          )}
        </div>
      ))}
      {data.history.map((h) => (
        <p key={h.id} className="mt-3 text-xs text-slate-500">
          {h.decision.toLowerCase()} · {h.created_at} · {h.details.reason}
        </p>
      ))}
    </section>
  );
}
