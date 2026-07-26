import { FormEvent, useState } from "react";
import { askChat, ChatResponse, resetChatSessionId } from "./api";

const SUGGESTIONS = [
  "Pods nào đang cao tải nhất?",
  "Node nào đang đầy disk?",
  "PVC nào dùng trên 80%?",
  "Có pod nào CrashLoopBackOff không?",
  "Why is Payment Service down?",
];

type Props = { onRemediationsChanged?: () => void };

export function ChatPanel({ onRemediationsChanged }: Props) {
  const [question, setQuestion] = useState("Pods nào đang cao tải nhất?");
  const [namespace, setNamespace] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ChatResponse | null>(null);

  async function runAsk(q: string) {
    setLoading(true);
    setError(null);
    setQuestion(q);
    try {
      const data = await askChat(q, namespace.trim() || undefined);
      setResult(data);
      onRemediationsChanged?.();
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await runAsk(question);
  }

  function onNewChat() {
    resetChatSessionId();
    setResult(null);
    setError(null);
  }

  const confidencePct =
    result?.confidence != null ? Math.round(result.confidence * 100) : null;
  const symptomPct =
    result?.symptom_confidence != null ? Math.round(result.symptom_confidence * 100) : null;
  const rootPct =
    result?.root_cause_confidence != null
      ? Math.round(result.root_cause_confidence * 100)
      : null;
  const followups = result?.suggested_followups?.filter(Boolean) || [];

  return (
    <div className="panel">
      <div className="hero-kicker">Ops assistant · Phase 6</div>
      <h1>Ask the platform</h1>
      <p className="lead">
        Multi-turn ops Q&amp;A. Context pack (metrics, failures, events, PVC, HPA) + session memory.
        Restart tạo pending remediation — không tự chạy.
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
                const low = s.toLowerCase();
                if (low.includes("movie")) setNamespace("npd-movie");
                else if (
                  low.includes("payment") ||
                  low.includes("npd-banking") ||
                  low.includes("banking")
                )
                  setNamespace("npd-banking");
                else setNamespace("");
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
            placeholder="Hỏi gì cũng được: CPU, node, deployment, CrashLoop, PVC, HPA, restart…"
            required
          />
          <div className="row">
            <div className="field">
              <label htmlFor="ns">Namespace (optional — trống = cluster)</label>
              <input
                id="ns"
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
                placeholder="npd-banking hoặc để trống"
              />
            </div>
            <button type="button" className="btn" onClick={onNewChat} disabled={loading}>
              New chat
            </button>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={loading || !question.trim()}
            >
              {loading ? "Querying…" : "Ask"}
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
                {result.ops_snapshot?.mode && (
                  <span className="badge ok">{result.ops_snapshot.mode}</span>
                )}
                {result.session_id && (
                  <span className="badge" title={result.session_id}>
                    session
                  </span>
                )}
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

          {(() => {
            const items = Array.isArray(result.evidence)
              ? result.evidence.filter((e) => typeof e === "string" && e.length > 1)
              : typeof result.evidence === "string" && result.evidence
                ? [result.evidence]
                : [];
            if (!items.length) return null;
            return (
              <>
                <div className="section-title">Evidence stream</div>
                <ul className="evidence">
                  {items.map((e, i) => (
                    <li key={`${i}-${e.slice(0, 24)}`}>{e}</li>
                  ))}
                </ul>
              </>
            );
          })()}

          {result.recommendation && (
            <div className="rec">
              <strong>Recommendation</strong>
              <div>{result.recommendation}</div>
            </div>
          )}

          {followups.length > 0 && (
            <>
              <div className="section-title" style={{ marginTop: "1.25rem" }}>
                Ask next
              </div>
              <div className="chips">
                {followups.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="chip"
                    disabled={loading}
                    onClick={() => void runAsk(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </>
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
