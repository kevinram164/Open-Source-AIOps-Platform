import type { IncidentTopology, TopologyNeighbor } from "./api";
import { shortLabel } from "./topologyMermaid";

function neighborKey(n: TopologyNeighbor): string {
  if (n.id) return shortLabel(n.id);
  if (n.namespace && n.name) return `${n.namespace}/${n.name}`;
  return n.name || "unknown";
}

function NodeChip({
  label,
  meta,
  tone,
}: {
  label: string;
  meta?: string;
  tone: "affected" | "fault" | "dep";
}) {
  return (
    <div className={`blast-chip blast-chip--${tone}`}>
      <span className="blast-chip-label">{label}</span>
      {meta ? <span className="blast-chip-meta">{meta}</span> : null}
    </div>
  );
}

type Props = {
  topo: IncidentTopology;
  fallbackWorkload?: string | null;
};

/** Compact 3-column blast map: affected | fault | deps */
export function BlastRadiusGraph({ topo, fallbackWorkload }: Props) {
  const centerLabel =
    (topo.center?.namespace && topo.center?.name
      ? `${topo.center.namespace}/${topo.center.name}`
      : shortLabel(topo.center?.id || "") ||
        topo.center?.name ||
        fallbackWorkload ||
        "incident");

  const upstream = (topo.upstream || []).slice(0, 10);
  const downstream = (topo.downstream || []).slice(0, 10);

  return (
    <div className="blast-map" role="img" aria-label="Blast radius: affected, fault, dependencies">
      <div className="blast-map-col blast-map-col--affected">
        <div className="blast-map-col-title">Bị ảnh hưởng</div>
        {upstream.length === 0 && <p className="blast-map-empty">Không có</p>}
        {upstream.map((n) => (
          <NodeChip
            key={neighborKey(n)}
            label={neighborKey(n)}
            meta={[n.hops != null ? `${n.hops} hop` : "", n.kind || ""].filter(Boolean).join(" · ")}
            tone="affected"
          />
        ))}
      </div>

      <div className="blast-map-flow" aria-hidden>
        <span className="blast-flow-line blast-flow-line--in" />
      </div>

      <div className="blast-map-col blast-map-col--center">
        <div className="blast-map-col-title">Sự cố</div>
        <NodeChip label={centerLabel} tone="fault" />
      </div>

      <div className="blast-map-flow" aria-hidden>
        <span className="blast-flow-line blast-flow-line--out" />
      </div>

      <div className="blast-map-col blast-map-col--dep">
        <div className="blast-map-col-title">Dependency</div>
        {downstream.length === 0 && <p className="blast-map-empty">Không có</p>}
        {downstream.map((n) => (
          <NodeChip
            key={neighborKey(n)}
            label={neighborKey(n)}
            meta={[n.hops != null ? `${n.hops} hop` : "", n.kind || ""].filter(Boolean).join(" · ")}
            tone="dep"
          />
        ))}
      </div>
    </div>
  );
}
