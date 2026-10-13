"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Panel, Table, Td, Th } from "@/components/ui";
import { send } from "@/lib/api-browser";
import type { components } from "@/lib/api-schema";

type User = components["schemas"]["UserView"];

const ROLES = ["admin", "researcher", "moderator", "publisher", "analyst"] as const;

/** Users and roles (admin only). One person may hold several roles; every action records the role that allowed it. */
export function UserForms({ users, myId }: { users: User[]; myId: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [roles, setRoles] = useState<string[]>(["moderator"]);

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const result = await send("POST", "/v1/admin/users", {
      email: String(data.get("email") ?? ""),
      display_name: String(data.get("display_name") ?? ""),
      roles,
      password: String(data.get("password") ?? ""),
    });
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setError(null);
    form.reset();
    router.refresh();
  }

  async function update(user: User, change: Partial<Pick<User, "roles" | "active">>) {
    const result = await send("PATCH", `/v1/admin/users/${user.id}`, change);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setError(null);
    router.refresh();
  }

  return (
    <Panel title="Users and roles">
      {error ? (
        <p role="alert" className="mb-2 text-danger">
          {error}
        </p>
      ) : null}
      <Table label="Users">
        <thead>
          <tr>
            <Th>User</Th>
            {ROLES.map((r) => (
              <Th key={r}>{r}</Th>
            ))}
            <Th>Access</Th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <Td>
                {u.display_name}
                <div className="text-ink-muted">{u.email}</div>
              </Td>
              {ROLES.map((r) => (
                <Td key={r}>
                  <input
                    type="checkbox"
                    aria-label={`${u.email} ${r}`}
                    checked={u.roles.includes(r)}
                    disabled={u.id === myId && r === "admin"}
                    onChange={(e) => {
                      const next = e.target.checked ? [...u.roles, r] : u.roles.filter((x) => x !== r);
                      if (next.length) void update(u, { roles: next });
                    }}
                  />
                </Td>
              ))}
              <Td>
                {u.id === myId ? (
                  <span className="text-ink-muted">you</span>
                ) : (
                  <button type="button" className="underline" onClick={() => void update(u, { active: !u.active })}>
                    {u.active ? "deactivate" : "reactivate"}
                  </button>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <form onSubmit={create} className="mt-4 flex flex-wrap items-end gap-3" aria-label="New user">
        <label>
          <span className="mb-1 block text-ink-muted">E-mail</span>
          <input name="email" type="email" required className="rounded border border-line px-2 py-1" />
        </label>
        <label>
          <span className="mb-1 block text-ink-muted">Name</span>
          <input name="display_name" required className="rounded border border-line px-2 py-1" />
        </label>
        <label>
          <span className="mb-1 block text-ink-muted">Password (12+ characters)</span>
          <input name="password" type="password" minLength={12} required autoComplete="new-password" className="rounded border border-line px-2 py-1" />
        </label>
        <fieldset className="flex gap-2">
          <legend className="mb-1 text-ink-muted">Roles</legend>
          {ROLES.map((r) => (
            <label key={r} className="flex items-center gap-1">
              <input type="checkbox" checked={roles.includes(r)} onChange={(e) => setRoles(e.target.checked ? [...roles, r] : roles.filter((x) => x !== r))} />
              {r}
            </label>
          ))}
        </fieldset>
        <button type="submit" className="rounded bg-accent px-3 py-1 text-white">
          Create user
        </button>
      </form>
    </Panel>
  );
}
