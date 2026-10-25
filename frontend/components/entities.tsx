"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { api, allRecords } from "@/lib/api";
import type { Brand, Campaign, Creator, Invoice } from "@/lib/types";
import { money } from "@/lib/utils";
import { ErrorNotice, Loading, useWorkspace } from "./workspace";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { RelatedRecords } from "./related-records";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "./ui/dialog";

type Kind = "brands" | "creators" | "campaigns" | "invoices";
type Row = Brand | Creator | Campaign | Invoice;
type Field = {
  key: string;
  label: string;
  type?: string;
  default?: string;
  options?: { value: string; label: string }[];
  optional?: boolean;
  pattern?: string;
  maxLength?: number;
};
const names = {
  brands: "Brand",
  creators: "Creator",
  campaigns: "Campaign",
  invoices: "Invoice",
};
const roles: Record<Kind, string[]> = {
  brands: ["OWNER", "ADMIN", "FINANCE"],
  creators: ["OWNER", "ADMIN", "OPS"],
  campaigns: ["OWNER", "ADMIN", "OPS"],
  invoices: ["OWNER", "ADMIN", "FINANCE"],
};

export function EntityPage({ kind }: { kind: Kind }) {
  const { agency } = useWorkspace();
  const [rows, setRows] = useState<Row[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [creators, setCreators] = useState<Creator[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Row>();
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [deleting, setDeleting] = useState<Row>();
  const [detail, setDetail] = useState<Row>();
  const writable = roles[kind].includes(agency.role);
  async function load() {
    setLoading(true);
    setError("");
    try {
      const results = await Promise.all([
        api<Row[]>(`/${kind}?offset=${offset}`, { agency: agency.id }),
        allRecords<Brand>("/brands", agency.id),
        allRecords<Creator>("/creators", agency.id),
        allRecords<Campaign>("/campaigns", agency.id),
      ]);
      setRows(results[0].data);
      setBrands(results[1].data);
      setCreators(results[2].data);
      setCampaigns(results[3].data);
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Unable to load records",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void Promise.resolve().then(load);
  }, [agency.id, kind, offset]); // eslint-disable-line react-hooks/exhaustive-deps
  const currency = {
    key: "currency",
    label: "Currency",
    default: agency.default_currency,
    pattern: "[A-Z]{3}",
    maxLength: 3,
  };
  const notes = {
    key: "notes",
    label: "Notes",
    type: "textarea",
    optional: true,
  };
  const description = {
    key: "description",
    label: "Description",
    type: "textarea",
    optional: true,
  };
  const brandField = {
    key: "brand_id",
    label: "Brand",
    options: brands.map((b) => ({ value: b.id, label: b.name })),
  };
  const fields: Record<Kind, Field[]> = {
    brands: [
      { key: "name", label: "Brand name" },
      { key: "contact_name", label: "Contact name", optional: true },
      { key: "contact_email", label: "Contact email", type: "email" },
      {
        key: "payment_terms_days",
        label: "Payment terms (days)",
        type: "number",
        default: "30",
      },
      notes,
    ],
    creators: [
      { key: "name", label: "Creator name" },
      { key: "email", label: "Email", type: "email" },
      {
        key: "default_payout_percentage",
        label: "Payout percentage",
        default: "80.00",
        pattern: "[0-9]+(\\.[0-9]{1,2})?",
      },
      notes,
    ],
    campaigns: [
      { key: "name", label: "Campaign name" },
      brandField,
      {
        key: "creator_id",
        label: "Creator",
        options: creators.map((c) => ({ value: c.id, label: c.name })),
      },
      {
        key: "deal_value",
        label: "Deal value",
        pattern: "[0-9]+(\\.[0-9]{1,2})?",
      },
      currency,
      { key: "start_date", label: "Start date", type: "date" },
      { key: "end_date", label: "End date", type: "date" },
      {
        key: "status",
        label: "Status",
        default: "ACTIVE",
        options: ["DRAFT", "ACTIVE", "COMPLETED", "CANCELLED"].map((value) => ({
          value,
          label: value,
        })),
      },
      description,
    ],
    invoices: [
      {
        key: "payment_reference",
        label: "Expected payment reference",
        optional: true,
      },
      {
        key: "invoice_number",
        label: "Invoice number",
        pattern: "[A-Za-z0-9_-]+",
        maxLength: 80,
      },
      brandField,
      {
        key: "campaign_id",
        label: "Campaign",
        options: campaigns.map((c) => ({ value: c.id, label: c.name })),
      },
      { key: "amount", label: "Amount", pattern: "[0-9]+(\\.[0-9]{1,2})?" },
      currency,
      { key: "issue_date", label: "Issue date", type: "date" },
      { key: "due_date", label: "Due date", type: "date" },
      {
        key: "status",
        label: "Status",
        default: "SENT",
        options: ["DRAFT", "SENT", "DUE", "OVERDUE", "PAID", "VOID"].map(
          (value) => ({ value, label: value }),
        ),
      },
      description,
    ],
  };
  function value(row: Row, key: string) {
    return String((row as unknown as Record<string, unknown>)[key] ?? "");
  }
  function display(row: Row, key: string) {
    if (key === "brand_id")
      return brands.find((b) => b.id === value(row, key))?.name || "Brand";
    if (key === "creator_id")
      return creators.find((c) => c.id === value(row, key))?.name || "Creator";
    if (key === "campaign_id")
      return (
        campaigns.find((c) => c.id === value(row, key))?.name || "Campaign"
      );
    if (key === "amount" || key === "deal_value")
      return money(value(row, key), value(row, "currency"));
    return value(row, key);
  }
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setFormError("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const body: Record<string, unknown> = { ...values };
    if (kind === "brands")
      body.payment_terms_days = Number(values.payment_terms_days);
    try {
      await api(`/${kind}${editing ? `/${editing.id}` : ""}`, {
        agency: agency.id,
        method: editing ? "PATCH" : "POST",
        body,
      });
      setOpen(false);
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }
  const columns =
    kind === "brands"
      ? ["name", "contact_email", "payment_terms_days"]
      : kind === "creators"
        ? ["name", "email", "default_payout_percentage"]
        : kind === "campaigns"
          ? ["name", "brand_id", "creator_id", "deal_value", "status"]
          : ["invoice_number", "brand_id", "amount", "due_date", "status"];
  return (
    <>
      <div className="mb-7 flex items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-teal-700">
            Agency workspace
          </p>
          <h1 className="text-3xl font-semibold capitalize tracking-tight">
            {kind}
          </h1>
          <p className="mt-2 text-sm text-slate-500">
            {kind === "invoices"
              ? "Track issued invoices, due dates, and collection history."
              : `Manage your agency’s ${kind}.`}
          </p>
        </div>
        {writable && (
          <Button
            onClick={() => {
              setEditing(undefined);
              setFormError("");
              setOpen(true);
            }}
          >
            <Plus size={16} />
            New {names[kind].toLowerCase()}
          </Button>
        )}
      </div>
      {error && (
        <div className="mb-5">
          <ErrorNotice message={error} />
          <Button
            variant="outline"
            className="mt-3"
            onClick={() => void load()}
          >
            Retry
          </Button>
        </div>
      )}
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        {loading ? (
          <Loading label={`Loading ${kind}…`} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    {columns.map((key) => (
                      <th key={key}>
                        {fields[kind].find((f) => f.key === key)?.label}
                      </th>
                    ))}
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      {columns.map((key, i) => (
                        <td key={key} className={i === 0 ? "font-medium" : ""}>
                          {key === "status" ? (
                            <Badge status={value(row, key)} />
                          ) : (
                            display(row, key)
                          )}
                        </td>
                      ))}
                      <td>
                        <div className="flex items-center gap-2">
                          {kind === "invoices" ? (
                            <Link
                              className="mr-2 text-teal-800"
                              href={`/invoices/${row.id}`}
                            >
                              View
                            </Link>
                          ) : (
                            <button
                              className="mr-2 text-teal-800"
                              onClick={() => setDetail(row)}
                            >
                              View
                            </button>
                          )}
                          {writable && (
                            <>
                              <Button
                                variant="ghost"
                                aria-label={`Edit ${value(row, "name") || value(row, "invoice_number")}`}
                                onClick={() => {
                                  setEditing(row);
                                  setFormError("");
                                  setOpen(true);
                                }}
                              >
                                <Pencil size={14} />
                              </Button>
                              <Button
                                variant="ghost"
                                aria-label={`Delete ${value(row, "name") || value(row, "invoice_number")}`}
                                onClick={() => {
                                  setDeleting(row);
                                  setFormError("");
                                }}
                              >
                                <Trash2 size={14} />
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!rows.length && (
              <div className="p-14 text-center">
                <h2 className="font-medium">No {kind} yet</h2>
                <p className="mt-2 text-sm text-slate-500">
                  {writable
                    ? `Add your first ${names[kind].toLowerCase()} to get started.`
                    : "Your team’s records will appear here."}
                </p>
              </div>
            )}
            <div className="flex justify-between p-4">
              <Button
                variant="ghost"
                disabled={offset === 0}
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
          </>
        )}
      </section>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle className="text-xl font-semibold">
            {editing ? "Edit" : "New"} {names[kind].toLowerCase()}
          </DialogTitle>
          <DialogDescription className="mb-6 mt-2 text-sm text-slate-500">
            {kind === "invoices"
              ? "Invoice status follows the agency’s local date. Issued records are retained for audit."
              : "Required information for your agency workspace."}
          </DialogDescription>
          <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
            {fields[kind].map((field) => (
              <label
                key={field.key}
                className={field.type === "textarea" ? "sm:col-span-2" : ""}
              >
                {field.label}
                {field.options ? (
                  <select
                    aria-label={field.label}
                    name={field.key}
                    required
                    defaultValue={
                      editing ? value(editing, field.key) : field.default || ""
                    }
                  >
                    <option value="" disabled>
                      Select {field.label.toLowerCase()}
                    </option>
                    {field.options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                ) : field.type === "textarea" ? (
                  <textarea
                    name={field.key}
                    rows={3}
                    maxLength={5000}
                    defaultValue={editing ? value(editing, field.key) : ""}
                  />
                ) : (
                  <input
                    name={field.key}
                    type={field.type || "text"}
                    inputMode={
                      [
                        "amount",
                        "deal_value",
                        "default_payout_percentage",
                      ].includes(field.key)
                        ? "decimal"
                        : undefined
                    }
                    pattern={field.pattern}
                    maxLength={field.maxLength || 160}
                    required={!field.optional}
                    defaultValue={
                      editing ? value(editing, field.key) : field.default
                    }
                    min={field.type === "number" ? 0 : undefined}
                    max={field.type === "number" ? 365 : undefined}
                  />
                )}
              </label>
            ))}
            {formError && (
              <div className="sm:col-span-2">
                <ErrorNotice message={formError} />
              </div>
            )}
            <div className="mt-2 flex justify-end gap-3 sm:col-span-2">
              <Button
                variant="outline"
                type="button"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!deleting}
        onOpenChange={(open) => {
          if (!open) setDeleting(undefined);
        }}
      >
        <DialogContent>
          <DialogTitle className="text-xl font-semibold">
            Delete {names[kind].toLowerCase()}?
          </DialogTitle>
          <DialogDescription className="my-4 text-sm text-slate-500">
            Records with related data cannot be removed. Issued invoices should
            be voided to retain their audit trail.
          </DialogDescription>
          {formError && <ErrorNotice message={formError} />}
          <div className="mt-5 flex justify-end gap-3">
            <Button variant="outline" onClick={() => setDeleting(undefined)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api(`/${kind}/${deleting!.id}`, {
                    agency: agency.id,
                    method: "DELETE",
                  });
                  setDeleting(undefined);
                  await load();
                } catch (error) {
                  setFormError(
                    error instanceof Error ? error.message : "Could not delete",
                  );
                } finally {
                  setBusy(false);
                }
              }}
            >
              Delete
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!detail}
        onOpenChange={(open) => {
          if (!open) setDetail(undefined);
        }}
      >
        <DialogContent>
          <DialogTitle className="text-xl font-semibold">
            {detail ? value(detail, "name") : "Details"}
          </DialogTitle>
          <DialogDescription className="mb-5 mt-2 text-sm text-slate-500">
            {names[kind]} details and related records.
          </DialogDescription>
          {detail && (
            <>
              <dl className="grid gap-4 sm:grid-cols-2">
                {fields[kind].map((field) => (
                  <div key={field.key}>
                    <dt className="text-xs text-slate-500">{field.label}</dt>
                    <dd className="mt-1 break-words text-sm">
                      {display(detail, field.key) || "—"}
                    </dd>
                  </div>
                ))}
              </dl>
              <RelatedRecords kind={kind} id={detail.id} />
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
