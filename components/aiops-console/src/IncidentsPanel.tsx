import { useCallback, useEffect, useState } from "react";
import { Incident, listIncidents } from "./api";

export function IncidentsPanel() {
  const [items, setItems] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await listIncidents());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="panel">
      <div className="hero-kicker">Operations feed</div>
      <h1>Incidents</h1>
      <p className="lead">Correlated alerts landing in the AIOps incident store.</p>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => void load()}>
          Refresh
        </button>
      </div>
      {loading && <p className="loading">Loading…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Title</th>
                <th>Status</th>
                <th>Severity</th>
                <th>Namespace</th>
                <th>Workload</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id}>
                  <td>{i.external_id}</td>
                  <td>{i.title}</td>
                  <td>
                    <span className="badge">{i.status}</span>
                  </td>
                  <td>{i.severity}</td>
                  <td>{i.namespace || "—"}</td>
                  <td>{i.workload || "—"}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6}>No incidents yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
