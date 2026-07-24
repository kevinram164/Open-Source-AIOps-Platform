import { useState } from "react";
import { ChatPanel } from "./ChatPanel";
import { IncidentsPanel } from "./IncidentsPanel";
import { RemediationsPanel } from "./RemediationsPanel";

type Tab = "ask" | "incidents" | "remediations";

export default function App() {
  const [tab, setTab] = useState<Tab>("ask");
  const [remKey, setRemKey] = useState(0);

  return (
    <div className="stage">
      <div className="grid-overlay" aria-hidden />
      <div className="app">
        <aside className="sidebar">
          <div className="brand-block">
            <div className="brand">
              Open
              <br />
              <em>AIOps</em>
            </div>
            <div className="brand-sub">Command console</div>
            <div className="live-pill">
              <i aria-hidden />
              Cluster live · ocp01
            </div>
          </div>
          <nav className="nav">
            <button
              type="button"
              className={tab === "ask" ? "active" : ""}
              onClick={() => setTab("ask")}
            >
              Ask
            </button>
            <button
              type="button"
              className={tab === "incidents" ? "active" : ""}
              onClick={() => setTab("incidents")}
            >
              Incidents
            </button>
            <button
              type="button"
              className={tab === "remediations" ? "active" : ""}
              onClick={() => setTab("remediations")}
            >
              Remediations
            </button>
          </nav>
          <div className="sidebar-foot">
            Human-in-the-loop automation.
            <br />
            AI recommends — you approve.
          </div>
        </aside>
        <main className="main">
          <div className="watermark" aria-hidden>
            AIOps
          </div>
          {tab === "ask" && (
            <ChatPanel onRemediationsChanged={() => setRemKey((k) => k + 1)} />
          )}
          {tab === "incidents" && <IncidentsPanel />}
          {tab === "remediations" && <RemediationsPanel refreshKey={remKey} />}
        </main>
      </div>
    </div>
  );
}
