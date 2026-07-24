import { useCallback, useEffect, useState } from "react";
import {
  approveRemediation,
  executeRemediation,
  listRemediations,
  Remediation,
} from "./api";

type Props = { refreshKey?: number };

export function RemediationsPanel({ refreshKey = 0 }: Props) {
  const [items, setItems] = useState<Remediation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await listRemediations());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function onApprove(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await approveRemediation(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function onExecute(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await executeRemediation(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="panel">
      <div className="hero-kicker">Control plane</div>
      <h1>Remediations</h1>
      <p className="lead">
        Approve NBA drafts, then execute — restart, GitOps scale, or diagnostics runbook.
      </p>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => void load()}>
          Refresh
        </button>
      </div>
      {loading && <p className="loading">Loading…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Target</th>
                <th>Status</th>
                <th>Incident</th>
                <th>Reason</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td>
                    <code>{r.action}</code>
                  </td>
                  <td>
                    {r.namespace}/{r.target}
                  </td>
                  <td>
                    <span
                      className={
                        r.status === "pending"
                          ? "badge warn"
                          : r.status === "completed"
                            ? "badge ok"
                            : "badge"
                      }
                    >
                      {r.status}
                    </span>
                  </td>
                  <td>{r.incident_id || "—"}</td>
                  <td>{r.reason || r.result || r.error || "—"}</td>
                  <td>
                    <div className="actions">
                      {r.status === "pending" && (
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={busyId === r.id}
                          onClick={() => void onApprove(r.id)}
                        >
                          Approve
                        </button>
                      )}
                      {r.status === "approved" && (
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={busyId === r.id}
                          onClick={() => void onExecute(r.id)}
                        >
                          Execute
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6}>No remediations yet — ask in Chat to create NBA drafts.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
