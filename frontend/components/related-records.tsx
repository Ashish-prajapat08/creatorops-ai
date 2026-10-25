"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Campaign, Invoice } from "@/lib/types";
import { money } from "@/lib/utils";
import { ErrorNotice, Loading, useWorkspace } from "./workspace";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

export function RelatedRecords({
  kind,
  id,
}: {
  kind: "brands" | "creators" | "campaigns" | "invoices";
  id: string;
}) {
  const { agency } = useWorkspace();
  const [invoices, setInvoices] = useState<Invoice[]>();
  const [campaigns, setCampaigns] = useState<Campaign[]>();
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const filter =
          kind === "brands"
            ? "brand_id"
            : kind === "creators"
              ? "creator_id"
              : "campaign_id";
        if (kind === "brands" || kind === "creators")
          setCampaigns(
            (
              await api<Campaign[]>(
                `/campaigns?${filter}=${id}&offset=${offset}`,
                { agency: agency.id, signal: controller.signal },
              )
            ).data,
          );
        if (kind !== "creators")
          setInvoices(
            (
              await api<Invoice[]>(
                `/invoices?${filter}=${id}&offset=${offset}`,
                { agency: agency.id, signal: controller.signal },
              )
            ).data,
          );
      } catch (error) {
        if (!controller.signal.aborted)
          setError(
            error instanceof Error
              ? error.message
              : "Could not load related records",
          );
      }
    }
    void load();
    return () => controller.abort();
  }, [agency.id, id, kind, offset]);
  return (
    <section className="mt-6 border-t pt-5">
      {error && <ErrorNotice message={error} />}
      {(kind === "brands" || kind === "creators") && (
        <>
          <h3 className="mb-3 text-sm font-semibold">Campaigns</h3>
          {!campaigns ? (
            <Loading label="Loading related campaigns…" />
          ) : campaigns.length ? (
            campaigns.map((c) => (
              <p key={c.id} className="mb-3 text-sm">
                {c.name} · {money(c.deal_value, c.currency)} · {c.status}
              </p>
            ))
          ) : (
            <p className="mb-4 text-sm text-slate-500">No related campaigns.</p>
          )}
        </>
      )}
      {kind !== "creators" && (
        <>
          <h3 className="mb-3 mt-5 text-sm font-semibold">
            Invoices and collection history
          </h3>
          {!invoices ? (
            <Loading label="Loading related invoices…" />
          ) : invoices.length ? (
            invoices.map((invoice) => (
              <Link
                key={invoice.id}
                href={`/invoices/${invoice.id}`}
                className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm"
              >
                <span className="font-medium text-teal-800">
                  {invoice.invoice_number}
                </span>
                <span>{money(invoice.amount, invoice.currency)}</span>
                <Badge status={invoice.status} />
              </Link>
            ))
          ) : (
            <p className="text-sm text-slate-500">No related invoices.</p>
          )}
        </>
      )}
      <div className="mt-4 flex justify-between">
        <Button
          variant="ghost"
          disabled={!offset}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Previous
        </Button>
        <Button
          variant="ghost"
          disabled={
            (invoices?.length || 0) < 50 && (campaigns?.length || 0) < 50
          }
          onClick={() => setOffset(offset + 50)}
        >
          Next
        </Button>
      </div>
    </section>
  );
}
