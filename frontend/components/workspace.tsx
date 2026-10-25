"use client";
import { createContext, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Building2,
  ChartNoAxesCombined,
  FileText,
  Landmark,
  ListChecks,
  LogOut,
  Settings,
  ShieldCheck,
  Users,
  Megaphone,
  Mail,
  Wallet,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { signOut } from "@/lib/auth";
import type { Agency } from "@/lib/types";
import { Button } from "./ui/button";

type WorkspaceContext = {
  agency: Agency;
  agencies: Agency[];
  reload: () => Promise<void>;
};
const Context = createContext<WorkspaceContext | null>(null);
export function useWorkspace() {
  const value = useContext(Context);
  if (!value) throw new Error("Workspace is not ready");
  return value;
}
export const nav = [
  { href: "/dashboard", label: "Overview", icon: ChartNoAxesCombined },
  { href: "/invoices", label: "Invoices", icon: FileText },
  { href: "/collections", label: "Collections", icon: ListChecks },
  { href: "/email-intelligence", label: "Email intelligence", icon: Mail },
  { href: "/reconciliation", label: "Reconciliation", icon: Wallet },
  { href: "/brands", label: "Brands", icon: Building2 },
  { href: "/creators", label: "Creators", icon: Users },
  { href: "/campaigns", label: "Campaigns", icon: Megaphone },
  { href: "/audit", label: "Audit trail", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function WorkspaceForm({ done }: { done: () => Promise<void> }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const { data } = await api<Agency>("/agencies", {
        method: "POST",
        body: Object.fromEntries(form),
      });
      localStorage.setItem("creatorops-agency", data.id);
      await done();
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Could not create workspace",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="grid gap-4">
      <label>
        Agency name
        <input
          name="name"
          required
          maxLength={160}
          placeholder="Acme Creator Management"
        />
      </label>
      <label>
        Default currency
        <input
          name="default_currency"
          required
          pattern="[A-Z]{3}"
          defaultValue="USD"
          maxLength={3}
        />
      </label>
      <label>
        Timezone
        <input name="timezone" required defaultValue="Asia/Kolkata" />
      </label>
      {error && <ErrorNotice message={error} />}
      <Button disabled={busy}>{busy ? "Creating…" : "Create workspace"}</Button>
    </form>
  );
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      {message}
    </p>
  );
}
export function Loading({ label = "Loading workspace…" }: { label?: string }) {
  return (
    <p role="status" className="p-12 text-sm text-slate-500">
      {label}
    </p>
  );
}

export function Workspace({ children }: { children: React.ReactNode }) {
  const [agencies, setAgencies] = useState<Agency[]>([]);
  const [selected, setSelected] = useState("");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();
  const path = usePathname();
  async function reload() {
    try {
      await api("/auth/me");
      const { data } = await api<Agency[]>("/agencies");
      setAgencies(data);
      const id = localStorage.getItem("creatorops-agency");
      setSelected(data.find((a) => a.id === id)?.id || data[0]?.id || "");
      setError("");
    } catch (error) {
      if (error instanceof ApiError && error.code === "UNAUTHORIZED")
        router.replace("/login");
      else
        setError(
          error instanceof Error ? error.message : "Could not load workspace",
        );
    } finally {
      setReady(true);
    }
  }
  useEffect(() => {
    void Promise.resolve().then(reload);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const agency = agencies.find((a) => a.id === selected);
  if (!ready) return <Loading />;
  if (error)
    return (
      <main className="mx-auto mt-20 max-w-lg p-6">
        <ErrorNotice message={error} />
        <Button className="mt-4" onClick={() => void reload()}>
          Try again
        </Button>
        <Button variant="ghost" onClick={() => router.push("/login")}>
          Sign in
        </Button>
      </main>
    );
  if (!agency)
    return (
      <main className="mx-auto mt-20 max-w-lg rounded-xl border bg-white p-8">
        <h1 className="mb-2 text-2xl font-semibold">
          Create your agency workspace
        </h1>
        <p className="mb-6 text-sm text-slate-500">
          Set up the home for your brands, creators, and invoices.
        </p>
        <WorkspaceForm done={reload} />
      </main>
    );
  return (
    <Context.Provider value={{ agency, agencies, reload }}>
      <div className="min-h-screen md:flex">
        <aside className="flex flex-col border-r border-slate-200 bg-white p-5 md:fixed md:inset-y-0 md:w-60">
          <Link
            href="/dashboard"
            className="mb-8 flex items-center gap-2.5 text-lg font-semibold"
          >
            <span className="rounded-lg bg-teal-800 p-2 text-white">
              <Landmark size={19} />
            </span>
            CreatorOps <span className="text-teal-700">AI</span>
          </Link>
          <div className="mb-7 rounded-lg border border-slate-200 p-3">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-slate-400">
              Agency workspace
            </p>
            <select
              aria-label="Switch workspace"
              value={agency.id}
              onChange={(e) => {
                setSelected(e.target.value);
                localStorage.setItem("creatorops-agency", e.target.value);
              }}
              className="border-0 p-0 text-sm font-medium"
            >
              {agencies.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <p className="mt-2 text-[11px] text-slate-500">
              {agency.role.toLowerCase()}
            </p>
          </div>
          <nav className="flex gap-1 overflow-x-auto md:grid md:min-h-0 md:flex-1 md:content-start md:overflow-y-auto">
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded-md px-3 py-2.5 text-sm ${path.startsWith(item.href) ? "bg-teal-50 font-semibold text-teal-900" : "text-slate-500 hover:bg-slate-50"}`}
              >
                <item.icon size={17} />
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="mt-8 border-t border-slate-100 pt-5 md:mt-4 md:shrink-0">
            <p className="mb-3 text-xs text-slate-400">
              Human control. Complete history.
            </p>
            <button
              className="flex items-center gap-2 text-sm text-slate-500"
              onClick={async () => {
                await signOut();
                router.replace("/login");
              }}
            >
              <LogOut size={15} />
              Sign out
            </button>
          </div>
        </aside>
        <div className="min-w-0 flex-1 md:ml-60">
          <header className="flex items-center justify-between border-b border-slate-200 bg-white px-8 py-5">
            <p className="text-sm text-slate-500">
              Workspace <span className="mx-2 text-slate-300">/</span>
              <span className="font-medium text-slate-700">
                {nav.find((item) => path.startsWith(item.href))?.label ||
                  "Invoice details"}
              </span>
            </p>
            <span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-medium text-teal-800">
              {agency.default_currency} · {agency.timezone}
            </span>
          </header>
          <main key={agency.id} className="mx-auto max-w-7xl p-5 md:p-8">
            {children}
          </main>
        </div>
      </div>
    </Context.Provider>
  );
}
