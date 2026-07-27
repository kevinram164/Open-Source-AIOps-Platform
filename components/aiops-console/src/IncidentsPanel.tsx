import { useCallback, useEffect, useMemo, useState } from "react";
import { Incident, IncidentTopology, getIncidentTopology, listIncidents } from "./api";
import { MermaidBlock } from "./MermaidBlock";
import { topologyToMermaid } from "./topologyMermaid";

function NeighborList({
  title,
  hint,
  items,
}: {
  title: string;
  hint: string;
  items: { namespace?: string | null; name?: string | null; hops?: number | null; kind?: string | null }[];
}) {
  if (!items.length) return null;
  return (
    <div className="topo-col">
      <div className="topo-col-title">{title}</div>
      <p className="topo-col-hint">{hint}</p>
      <ul className="topo-list">
        {items.map((n) => (
          <li key={`${n.namespace}/${n.name}`}>
            <span className="topo-name">
              {n.namespace ? `${n.namespace}/` : ""}
              {n.name}
            </span>
            <span className="topo-meta">
              {n.hops != null ? `${n.hops} hop` : ""}
              {n.kind ? ` · ${n.kind}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function IncidentsPanel() {
  const [items, setItems] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Incident | null>(null);
  const [topo, setTopo] = useState<IncidentTopology | null>(null);
  const [topoError, setTopoError] = useState<string | null>(null);
  const [topoLoading, setTopoLoading] = useState(false);

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

  const openIncident = useCallback(async (inc: Incident) => {
    setSelected(inc);
    setTopo(null);
    setTopoError(null);
    setTopoLoading(true);
    try {
      setTopo(await getIncidentTopology(inc.id));
    } catch (err) {
      setTopoError(err instanceof Error ? err.message : String(err));
    } finally {
      setTopoLoading(false);
    }
  }, []);

  const mermaid = useMemo(() => (topo ? topologyToMermaid(topo) : ""), [topo]);

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
                <tr
                  key={i.id}
                  className={selected?.id === i.id ? "row-selected" : "row-clickable"}
                  onClick={() => void openIncident(i)}
                >
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

      {selected && (
        <div className="topo-panel" aria-live="polite">
          <div className="topo-header">
            <div>
              <div className="hero-kicker">Blast radius</div>
              <h2>
                {selected.external_id}
                {selected.workload ? ` · ${selected.workload}` : ""}
              </h2>
              <p className="muted">
                Sơ đồ: trái = dịch vụ bị ảnh hưởng khi center lỗi · phải = dependency center cần để chạy.
              </p>
            </div>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>
              Close
            </button>
          </div>
          {topoLoading && <p className="loading">Loading topology…</p>}
          {topoError && <p className="error">{topoError}</p>}
          {topo && !topoLoading && (
            <>
              <div className="topo-center">
                <span className="topo-center-label">Sự cố tại</span>
                <span className="topo-center-id">
                  {(topo.center?.namespace ? `${topo.center.namespace}/` : "") +
                    (topo.center?.name || selected.workload || "—")}
                </span>
                <span className="badge">{topo.source || "unknown"}</span>
              </div>

              <div className="topo-legend">
                <span className="topo-leg topo-leg-caller">Caller — bị ảnh hưởng</span>
                <span className="topo-leg topo-leg-center">Center — sự cố</span>
                <span className="topo-leg topo-leg-dep">Dep — cần để chạy</span>
              </div>

              {mermaid && (
                <div className="topo-diagram">
                  <MermaidBlock chart={mermaid} />
                </div>
              )}

              <div className="topo-grid">
                <NeighborList
                  title="Bị ảnh hưởng (callers)"
                  hint="Gọi vào center — user/API có thể lỗi theo."
                  items={topo.upstream || []}
                />
                <NeighborList
                  title="Cần để chạy (dependencies)"
                  hint="Center phụ thuộc — kiểm tra khi RCA."
                  items={topo.downstream || []}
                />
              </div>
              {!topo.upstream?.length && !topo.downstream?.length && (
                <p className="muted">No neighbors in topology graph for this workload.</p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
