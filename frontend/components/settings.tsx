"use client";
import { useEffect, useState } from "react";
import { Mail, Plus, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { Member, Role } from "@/lib/types";
import { ErrorNotice, Loading, useWorkspace, WorkspaceForm } from "./workspace";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "./ui/dialog";

export function SettingsPage() {
  const { agency, reload } = useWorkspace();
  const [integration, setIntegration] = useState<{
    status: string;
    external_account_id?: string;
  }>();
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newWorkspace, setNewWorkspace] = useState(false);
  const [removing, setRemoving] = useState<Member>();
  const admin = ["OWNER", "ADMIN"].includes(agency.role);
  async function load() {
    try {
      const [i, m] = await Promise.all([
        api<{ status: string; external_account_id?: string }>(
          "/integrations/gmail",
          { agency: agency.id },
        ),
        api<Member[]>("/agencies/members", { agency: agency.id }),
      ]);
      setIntegration(i.data);
      setMembers(m.data);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Settings unavailable");
    }
  }
  useEffect(() => {
    void Promise.resolve().then(load);
  }, [agency.id]); // eslint-disable-line react-hooks/exhaustive-deps
  async function addMember(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    setError("");
    try {
      await api("/agencies/members", {
        agency: agency.id,
        method: "POST",
        body: Object.fromEntries(form),
      });
      formElement.reset();
      await load();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not add member");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="mb-7 flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-semibold">Workspace settings</h1>
          <p className="mt-2 text-sm text-slate-500">
            Manage Gmail access and your agency team.
          </p>
        </div>
        <Button variant="outline" onClick={() => setNewWorkspace(true)}>
          <Plus size={15} />
          New workspace
        </Button>
      </div>
      {error && (
        <div className="mb-5">
          <ErrorNotice message={error} />
        </div>
      )}
      <section className="mb-6 rounded-xl border bg-white p-6">
        <div className="mb-4 flex items-center gap-3">
          <Mail size={20} className="text-teal-800" />
          <h2 className="font-semibold">Gmail integration</h2>
        </div>
        {!integration ? (
          <Loading label="Loading Gmail connection…" />
        ) : (
          <>
            <p className="text-sm text-slate-600">
              {integration.status === "CONNECTED"
                ? `Connected: ${integration.external_account_id}`
                : integration.status === "RECONNECT_REQUIRED"
                  ? "Gmail needs to be reconnected."
                  : "Connect your agency Gmail to retrieve relevant context and send approved follow-ups."}
            </p>
            <p className="mb-5 mt-2 text-xs text-slate-400">
              Read-only mailbox access and email sending. Only relevant invoice
              messages are stored. OAuth tokens stay encrypted on the server.
            </p>
            {admin && (
              <div className="flex gap-3">
                <Button
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    setError("");
                    try {
                      const { data } = await api<{ url: string }>(
                        "/integrations/gmail/connect",
                        { agency: agency.id, method: "POST" },
                      );
                      window.location.assign(data.url);
                    } catch (error) {
                      setError(
                        error instanceof Error
                          ? error.message
                          : "Connection failed",
                      );
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {integration.status === "CONNECTED"
                    ? "Reconnect Gmail"
                    : "Connect Gmail"}
                </Button>
                {integration.status === "CONNECTED" && (
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await api("/integrations/gmail", {
                          agency: agency.id,
                          method: "DELETE",
                        });
                        await load();
                      } catch (error) {
                        setError(
                          error instanceof Error
                            ? error.message
                            : "Could not disconnect",
                        );
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Disconnect
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </section>
      <section className="rounded-xl border bg-white p-6">
        <h2 className="mb-4 flex items-center gap-3 font-semibold">
          <ShieldCheck size={20} className="text-teal-800" />
          Workspace members
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {members.map((member) => (
                <tr key={member.id}>
                  <td>{member.name}</td>
                  <td>{member.email}</td>
                  <td>{member.role}</td>
                  <td>
                    {admin && (
                      <Button
                        variant="ghost"
                        onClick={() => setRemoving(member)}
                      >
                        Remove
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {admin && (
          <form
            onSubmit={addMember}
            className="mt-6 grid items-end gap-4 sm:grid-cols-[1fr_160px_auto]"
          >
            <label>
              Member email
              <input name="email" type="email" required />
            </label>
            <label>
              Role
              <select name="role" defaultValue="VIEWER">
                {(
                  [
                    "VIEWER",
                    "OPS",
                    "FINANCE",
                    "ADMIN",
                    ...(agency.role === "OWNER" ? ["OWNER"] : []),
                  ] as Role[]
                ).map((role) => (
                  <option key={role}>{role}</option>
                ))}
              </select>
            </label>
            <Button disabled={busy}>Add member</Button>
            <p className="text-xs text-slate-400 sm:col-span-3">
              Members must sign up and access the app before they can be added.
              Finance approves sends; operations can prepare drafts; viewers
              have read-only access.
            </p>
          </form>
        )}
      </section>
      <Dialog open={newWorkspace} onOpenChange={setNewWorkspace}>
        <DialogContent>
          <DialogTitle className="text-xl font-semibold">
            New agency workspace
          </DialogTitle>
          <DialogDescription className="mb-5 mt-2 text-sm text-slate-500">
            Each workspace has separate records, members, and integrations.
          </DialogDescription>
          <WorkspaceForm
            done={async () => {
              await reload();
              setNewWorkspace(false);
            }}
          />
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!removing}
        onOpenChange={(open) => {
          if (!open) setRemoving(undefined);
        }}
      >
        <DialogContent>
          <DialogTitle className="text-xl font-semibold">
            Remove member?
          </DialogTitle>
          <DialogDescription className="my-4 text-sm text-slate-500">
            {removing?.email} will lose access to this agency workspace.
          </DialogDescription>
          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={() => setRemoving(undefined)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api(`/agencies/members/${removing!.id}`, {
                    agency: agency.id,
                    method: "DELETE",
                  });
                  setRemoving(undefined);
                  await load();
                } catch (error) {
                  setError(
                    error instanceof Error
                      ? error.message
                      : "Could not remove member",
                  );
                  setRemoving(undefined);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Remove
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
