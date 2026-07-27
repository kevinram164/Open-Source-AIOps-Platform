import { useEffect, useId, useRef, useState } from "react";

type Props = { chart: string };

/** Renders a Mermaid flowchart (Phase 7C). */
export function MermaidBlock({ chart }: Props) {
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
        });
        const { svg } = await mermaid.render(`mmd-${id}`, chart);
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
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
  }, [chart, id]);

  if (error) {
    return (
      <pre className="mermaid-fallback" title={error}>
        {chart}
      </pre>
    );
  }

  return <div className="mermaid-wrap" ref={ref} aria-label="Service topology diagram" />;
}
