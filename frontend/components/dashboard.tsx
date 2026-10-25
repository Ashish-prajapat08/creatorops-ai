"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CircleDollarSign, Clock3, ListChecks } from "lucide-react";
import { api, allRecords } from "@/lib/api";
import type { Brand, Summary } from "@/lib/types";
import { money } from "@/lib/utils";
import { ErrorNotice, Loading, useWorkspace } from "./workspace";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";

export function Dashboard() {
  const { agency } = useWorkspace();
  const [data, setData] = useState<Summary>();
  const [brands, setBrands] = useState<Brand[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([
      api<Summary>("/dashboard/summary", { agency: agency.id }),
      allRecords<Brand>("/brands", agency.id),
    ])
      .then(([summary, brands]) => {
        if (active) {
          setData(summary.data);
          setBrands(brands.data);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [agency.id]);
  if (error) return <ErrorNotice message={error} />;
  if (!data) return <Loading label="Loading financial overview…" />;
  const cards = [
    {
      key: "total_outstanding",
      label: "Outstanding",
      help: "Open issued invoices",
      icon: CircleDollarSign,
    },
    {
      key: "overdue_amount",
      label: "Overdue",
      help: "Past the payment due date",
      icon: Clock3,
    },
    {
      key: "due_soon_amount",
      label: "Due soon",
      help: "Within the next seven days",
      icon: Clock3,
    },
    {
      key: "paid_amount",
      label: "Paid",
      help: "Recorded as paid",
      icon: CircleDollarSign,
    },
  ] as const;
  return (
    <>
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-teal-700">
            Financial operations
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">
            Agency overview
          </h1>
          <p className="mt-2 text-sm text-slate-500">
            A clear view of what’s owed and what needs attention.
          </p>
        </div>
        <Button asChild>
          <Link href="/invoices">
            Manage invoices <ArrowRight size={15} />
          </Link>
        </Button>
      </div>
      {data.totals.length === 0 && (
        <div className="mb-6 rounded-xl border bg-white p-8">
          <h2 className="font-semibold">Your financial overview starts here</h2>
          <p className="mt-2 text-sm text-slate-500">
            Add a brand, creator, campaign, and invoice to start tracking
            collections.
          </p>
        </div>
      )}
      {data.totals.map((group) => (
        <section key={group.currency} className="mb-7">
          <p className="mb-3 text-xs font-semibold text-slate-500">
            {group.currency} ledger
          </p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {cards.map((card) => (
              <div
                key={card.key}
                className="rounded-xl border border-slate-200 bg-white p-5"
              >
                <div className="mb-5 flex items-center justify-between text-slate-500">
                  <span className="text-sm">{card.label}</span>
                  <card.icon size={18} />
                </div>
                <p
                  className={`text-2xl font-semibold tracking-tight ${card.key === "overdue_amount" ? "text-red-700" : "text-slate-800"}`}
                >
                  {money(group[card.key], group.currency)}
                </p>
                <p className="mt-2 text-xs text-slate-400">{card.help}</p>
              </div>
            ))}
          </div>
        </section>
      ))}
      <div className="mb-7 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-purple-100 bg-purple-50/60 p-5">
        <div className="flex items-center gap-4">
          <span className="rounded-lg bg-white p-3 text-purple-700">
            <ListChecks size={21} />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-purple-900">
              {data.pending_approval_count} collection drafts awaiting approval
            </h2>
            <p className="mt-1 text-xs text-purple-700">
              Review the context and exact email before anything is sent.
            </p>
          </div>
        </div>
        <Button variant="outline" asChild>
          <Link href="/collections">
            Review collections <ArrowRight size={14} />
          </Link>
        </Button>
      </div>
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between p-5">
          <div>
            <h2 className="font-semibold">
              Overdue invoices{" "}
              <span className="ml-2 rounded bg-red-50 px-2 py-1 text-xs text-red-700">
                {data.overdue_invoice_count}
              </span>
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Prioritize the invoices that need a follow-up.
            </p>
          </div>
          <Link className="text-xs font-medium text-teal-800" href="/invoices">
            All invoices →
          </Link>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Brand</th>
                <th>Amount</th>
                <th>Due date</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.overdue_invoices.map((invoice) => (
                <tr key={invoice.id}>
                  <td className="font-medium">{invoice.invoice_number}</td>
                  <td>
                    {brands.find((b) => b.id === invoice.brand_id)?.name ||
                      "Brand"}
                  </td>
                  <td className="font-medium tabular-nums">
                    {money(invoice.amount, invoice.currency)}
                  </td>
                  <td>{invoice.due_date}</td>
                  <td>
                    <Badge status="OVERDUE" />
                  </td>
                  <td>
                    <Link
                      href={`/invoices/${invoice.id}`}
                      className="text-teal-800"
                    >
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!data.overdue_invoices.length && (
          <p className="p-10 text-center text-sm text-slate-500">
            No overdue invoices. Your collections are up to date.
          </p>
        )}
      </section>
    </>
  );
}
