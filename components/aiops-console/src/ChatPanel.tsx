import { FormEvent, useState } from "react";
import { askChat, ChatResponse } from "./api";

const SUGGESTIONS = [
  "Why is Payment Service down?",
  "Có điều gì đáng lưu ý không?",
  "Có pod nào bị CrashLoopBackOff không?",
  "restart transfer-service in npd-banking",
];

type Props = { onRemediationsChanged?: () => void };

export function ChatPanel({ onRemediationsChanged }: Props) {
  const [question, setQuestion] = useState("Why is Payment Service down?");
  const [namespace, setNamespace] = useState("npd-banking");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ChatResponse | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const data = await askChat(question, namespace.trim() || undefined);
      setResult(data);
      onRemediationsChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const confidencePct =
    result?.confidence != null ? Math.round(result.confidence * 100) : null;
  const symptomPct =
    result?.symptom_confidence != null ? Math.round(result.symptom_confidence * 100) : null;
  const rootPct =
    result?.root_cause_confidence != null
      ? Math.round(result.root_cause_confidence * 100)
      : null;

  return (
    <div className="panel">
      <div className="hero-kicker">Situation room</div>
      <h1>Ask the platform</h1>
      <p className="lead">
        Incident investigator + ops Q&amp;A. Commands like restart create pending remediations —
        never silent auto-run.
      </p>

      <div className="ask-shell">
        <div className="chips">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              className="chip"
              onClick={() => {
                setQuestion(s);
                if (s.toLowerCase().includes("movie")) setNamespace("npd-movie");
                else if (s.toLowerCase().includes("đáng lưu ý") || s.toLowerCase().includes("crashloop"))
                  setNamespace("");
                else setNamespace("npd-banking");
              }}
            >
              {s}
            </button>
          ))}
        </div>

        <form className="chat-form" onSubmit={onSubmit}>
          <textarea
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask why a service is down…"
            required
          />
          <div className="row">
            <div className="field">
              <label htmlFor="ns">Namespace</label>
              <input
                id="ns"
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
                placeholder="npd-banking"
              />
            </div>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={loading || !question.trim()}
            >
              {loading ? "Correlating…" : "Run analysis"}
            </button>
          </div>
        </form>

        {loading && (
          <div className="scanning" aria-live="polite">
            <span>scanning evidence</span>
            <div className="scan-bar">
              <span />
            </div>
          </div>
        )}
      </div>

      {error && <p className="error">{error}</p>}

      {result && !loading && (
        <article className="result">
          <div className="result-head">
            <div>
              <h2>Investigator briefing</h2>
              <div className="meta">
                {result.intent && <span className="badge">{result.intent}</span>}
                {result.error_subtype && (
                  <span className="badge warn">{result.error_subtype}</span>
                )}
                {result.incident && (
                  <span className="badge ok">{result.incident.external_id}</span>
                )}
                {result.model && <span className="badge">{result.model}</span>}
                {result.incident?.namespace && (
                  <span className="badge">{result.incident.namespace}</span>
                )}
                {result.incident?.workload && (
                  <span className="badge">{result.incident.workload}</span>
                )}
              </div>
            </div>
            {confidencePct != null && (
              <div className="confidence" style={{ ["--p" as string]: confidencePct }}>
                <strong>{confidencePct}%</strong>
              </div>
            )}
          </div>

          {(result.symptom || result.probable_root_cause) && (
            <div className="rec" style={{ marginBottom: "1rem" }}>
              {result.symptom && (
                <div>
                  <strong>Symptom{symptomPct != null ? ` · ${symptomPct}%` : ""}</strong>
                  <div>{result.symptom}</div>
                </div>
              )}
              {result.probable_root_cause && (
                <div style={{ marginTop: result.symptom ? "0.75rem" : 0 }}>
                  <strong>
                    Root cause{rootPct != null ? ` · ${rootPct}%` : ""}
                  </strong>
                  <div>{result.probable_root_cause}</div>
                </div>
              )}
              {result.impact_scope && (
                <div style={{ marginTop: "0.75rem" }}>
                  <strong>Impact scope</strong>
                  <div>
                    {[
                      result.impact_scope.blast_radius &&
                        `blast=${result.impact_scope.blast_radius}`,
                      (result.impact_scope.namespaces || []).join(", "),
                      (result.impact_scope.workloads || []).join(", "),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="answer">{result.answer}</div>

          {result.evidence?.length > 0 && (
            <>
              <div className="section-title">Evidence stream</div>
              <ul className="evidence">
                {result.evidence.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </>
          )}

          {result.recommendation && (
            <div className="rec">
              <strong>Recommendation</strong>
              <div>{result.recommendation}</div>
            </div>
          )}

          {result.remediations?.length > 0 && (
            <>
              <div className="section-title" style={{ marginTop: "1.25rem" }}>
                Next best actions · pending approval
              </div>
              <div className="nba-strip">
                {result.remediations.map((r, i) => (
                  <div className="nba-item" key={r.id || String(i)}>
                    <div>
                      <code>{r.action}</code>
                      {r.namespace ? ` · ${r.namespace}/${r.target}` : ""}
                    </div>
                    <span className="badge warn">{r.status || "pending"}</span>
                  </div>
                ))}
              </div>
              <p className="lead" style={{ marginTop: "0.9rem", marginBottom: 0 }}>
                Switch to <strong>Remediations</strong> to approve &amp; execute.
              </p>
            </>
          )}
        </article>
      )}
    </div>
  );
}
