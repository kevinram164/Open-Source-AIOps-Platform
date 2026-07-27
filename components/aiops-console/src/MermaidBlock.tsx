import { useEffect, useId, useRef, useState } from "react";

type Props = {
  chart: string;
  className?: string;
  /** Animate edge strokes (flow along path) */
  animateFlow?: boolean;
};

/** Renders a Mermaid flowchart (Phase 7C). */
export function MermaidBlock({ chart, className, animateFlow }: Props) {
  const id = useId().replace(/:/g, "");
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function render() {
      if (!chart.trim() || !ref.current) return;
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "strict",
          fontFamily: "IBM Plex Sans, system-ui, sans-serif",
          themeVariables: {
            fontSize: "15px",
            fontFamily: "IBM Plex Sans, system-ui, sans-serif",
          },
          flowchart: {
            curve: "basis",
            padding: 20,
            nodeSpacing: 28,
            rankSpacing: 72,
            htmlLabels: true,
            useMaxWidth: false,
          },
        });
        const { svg } = await mermaid.render(`mmd-${id}-${Date.now()}`, chart);
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
          const svgEl = ref.current.querySelector("svg");
          if (svgEl) {
            svgEl.removeAttribute("width");
            svgEl.removeAttribute("height");
            svgEl.style.width = "100%";
            svgEl.style.maxWidth = "100%";
            svgEl.style.height = "auto";
            svgEl.style.minHeight = "520px";
          }
          if (animateFlow) {
            const edgeRoots = ref.current.querySelectorAll(
              ".edgePaths path, .flowchart-link, g.edgePath path",
            );
            edgeRoots.forEach((p) => p.classList.add("topo-edge-flow"));
          }
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }
    void render();
    return () => {
      cancelled = true;
    };
  }, [chart, id, animateFlow]);

  if (error) {
    return (
      <pre className="mermaid-fallback" title={error}>
        {chart}
      </pre>
    );
  }

  const cls = ["mermaid-wrap", className, animateFlow ? "mermaid-wrap--flow" : ""]
    .filter(Boolean)
    .join(" ");

  return <div className={cls} ref={ref} aria-label="Service topology diagram" />;
}
