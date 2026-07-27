import type { IncidentTopology, TopologyNeighbor } from "./api";

function mid(ref: string): string {
  return ref.replace(/[^a-zA-Z0-9_]/g, "_").slice(0, 64) || "node";
}

/** Prefer ns/name; strip Coroot cluster:ns:Kind:name → ns/name */
export function shortLabel(ref: string): string {
  const raw = (ref || "").replace(/"/g, "'");
  const parts = raw.split(":");
  if (parts.length >= 4) {
    const ns = parts[1];
    const name = parts.slice(3).join(":");
    return ns && name ? `${ns}/${name}` : name || raw;
  }
  if (raw.includes("/")) return raw;
  return raw;
}

function neighborId(n: TopologyNeighbor): string {
  if (n.id) return shortLabel(n.id);
  if (n.namespace && n.name) return `${n.namespace}/${n.name}`;
  return n.name || "unknown";
}

/**
 * Blast-radius Mermaid: callers (left) → incident center → dependencies (right).
 */
export function topologyToMermaid(topo: IncidentTopology): string {
  const center = topo.center || {};
  const cid =
    shortLabel(center.id || "") ||
    (center.namespace && center.name
      ? `${center.namespace}/${center.name}`
      : center.name || "incident");

  const upstream = (topo.upstream || []).slice(0, 12);
  const downstream = (topo.downstream || []).slice(0, 12);

  const lines: string[] = ["flowchart LR"];
  const declared = new Set<string>();

  function ensure(ref: string, cls?: string) {
    const label = shortLabel(ref);
    if (declared.has(label)) return mid(label);
    declared.add(label);
    const id = mid(label);
    if (cls) lines.push(`  ${id}["${label}"]:::${cls}`);
    else lines.push(`  ${id}["${label}"]`);
    return id;
  }

  const centerId = ensure(cid, "center");

  if (upstream.length) {
    lines.push("  subgraph CALLERS[\"Bị ảnh hưởng (gọi vào)\"]");
    lines.push("    direction TB");
    for (const n of upstream) {
      const nid = ensure(neighborId(n), "caller");
      lines.push(`    ${nid}`);
    }
    lines.push("  end");
    for (const n of upstream) {
      lines.push(`  ${mid(shortLabel(neighborId(n)))} -->|caller| ${centerId}`);
    }
  }

  if (downstream.length) {
    lines.push("  subgraph DEPS[\"Cần để chạy (dependency)\"]");
    lines.push("    direction TB");
    for (const n of downstream) {
      const nid = ensure(neighborId(n), "dep");
      lines.push(`    ${nid}`);
    }
    lines.push("  end");
    for (const n of downstream) {
      const kind = n.kind && n.kind !== "ebpf" && n.kind !== "dep" ? n.kind : "depends";
      lines.push(`  ${centerId} -->|${kind}| ${mid(shortLabel(neighborId(n)))}`);
    }
  }

  // Edge fallback if lists empty but edges exist
  if (!upstream.length && !downstream.length && topo.edges?.length) {
    for (const e of topo.edges.slice(0, 24)) {
      const frm = shortLabel(e.from);
      const to = shortLabel(e.to);
      ensure(frm);
      ensure(to);
      const kind = e.kind && e.kind !== "ebpf" ? e.kind : "";
      if (kind) lines.push(`  ${mid(frm)} -->|${kind}| ${mid(to)}`);
      else lines.push(`  ${mid(frm)} --> ${mid(to)}`);
    }
  }

  lines.push("  classDef center fill:#3ddc97,stroke:#0e1626,color:#060a12,font-weight:bold");
  lines.push("  classDef caller fill:#38bdf8,stroke:#0e1626,color:#060a12");
  lines.push("  classDef dep fill:#fbbf24,stroke:#0e1626,color:#060a12");
  return lines.join("\n");
}
