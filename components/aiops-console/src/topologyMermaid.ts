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
 * Blast-radius Mermaid:
 * left column (affected) · center (fault) · right column (deps)
 */
export function topologyToMermaid(topo: IncidentTopology): string {
  const center = topo.center || {};
  const cid =
    shortLabel(center.id || "") ||
    (center.namespace && center.name
      ? `${center.namespace}/${center.name}`
      : center.name || "incident");

  const upstream = (topo.upstream || []).slice(0, 8);
  const downstream = (topo.downstream || []).slice(0, 8);

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

  if (upstream.length) {
    lines.push('  subgraph CALLERS["Bị ảnh hưởng"]');
    lines.push("    direction TB");
    for (const n of upstream) {
      lines.push(`    ${ensure(neighborId(n), "affected")}`);
    }
    lines.push("  end");
  }

  const centerId = ensure(cid, "fault");

  if (downstream.length) {
    lines.push('  subgraph DEPS["Dependency"]');
    lines.push("    direction TB");
    for (const n of downstream) {
      lines.push(`    ${ensure(neighborId(n), "dep")}`);
    }
    lines.push("  end");
  }

  for (const n of upstream) {
    lines.push(`  ${mid(shortLabel(neighborId(n)))} ==> ${centerId}`);
  }
  for (const n of downstream) {
    lines.push(`  ${centerId} -.-> ${mid(shortLabel(neighborId(n)))}`);
  }

  if (!upstream.length && !downstream.length && topo.edges?.length) {
    for (const e of topo.edges.slice(0, 24)) {
      const frm = shortLabel(e.from);
      const to = shortLabel(e.to);
      ensure(frm);
      ensure(to);
      lines.push(`  ${mid(frm)} --> ${mid(to)}`);
    }
  }

  lines.push(
    "  classDef fault fill:#fb7185,stroke:#9f1239,color:#1a0508,font-weight:bold",
  );
  lines.push("  classDef affected fill:#fbbf24,stroke:#b45309,color:#1a1000");
  lines.push("  classDef dep fill:#94a3b8,stroke:#475569,color:#0f172a");
  return lines.join("\n");
}
