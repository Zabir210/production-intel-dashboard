import { useState, type FormEvent } from "react";
import { api, ApiError, type NLQResult } from "../api";

const EXAMPLES = [
  "Show nonconformances on line 3 last week",
  "Which stations had the most downtime in the last 14 days?",
  "Average cycle time vs standard by station on line 4 this month",
  "Daily finished units for line 1 over the last 10 days",
];

export default function QueryBar({ llmConfigured }: { llmConfigured: boolean }) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<NLQResult | null>(null);
  const [error, setError] = useState<{ message: string; sql?: string | null } | null>(null);
  const [busy, setBusy] = useState(false);

  async function ask(q: string) {
    if (!q.trim()) return;
    setQuestion(q);
    setBusy(true);
    setError(null);
    try {
      setResult(await api.ask(q));
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? { message: e.message, sql: e.sql } : { message: String(e) });
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); ask(question); };

  return (
    <div className="card">
      <div className="card-head"><span className="tag">Project 1</span><h3>Ask the data</h3></div>
      <p className="sub">
        Type a question. Claude writes one read-only SQL query; the server checks it and runs it against the
        dashboard tables, then shows you both the SQL and the rows so you can verify the answer.
      </p>
      <form className="ask" onSubmit={submit}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
               placeholder="e.g. show nonconformances on line 3 last week" aria-label="Question" />
        <button className="btn primary" disabled={busy || !question.trim()}>{busy ? "Thinking…" : "Ask"}</button>
      </form>
      <div className="examples">
        {EXAMPLES.map((q) => <button key={q} className="chip" onClick={() => ask(q)} disabled={busy}>{q}</button>)}
      </div>

      {!llmConfigured && (
        <div className="notice">
          The server has no <code>ANTHROPIC_API_KEY</code>, so questions will be refused. Add the key to
          <code> .env</code> and restart the API.
        </div>
      )}
      {error && (
        <>
          <div className="notice error">{error.message}</div>
          {error.sql && (<><div className="label-row"><span>SQL that was rejected</span></div><pre className="sql">{error.sql}</pre></>)}
        </>
      )}
      {result && (
        <div className={busy ? "loading" : ""}>
          {result.explanation && <p style={{ margin: "16px 0 0" }}>{result.explanation}</p>}
          <div className="label-row">
            <span>Generated SQL</span>
            <button className="chip" onClick={() => navigator.clipboard?.writeText(result.sql)}>Copy</button>
          </div>
          <pre className="sql">{result.sql}</pre>
          <div className="label-row">
            <span>{result.row_count.toLocaleString()} row{result.row_count === 1 ? "" : "s"}
              {result.truncated ? " (capped; refine the question to see the rest)" : ""}</span>
          </div>
          <ResultTable columns={result.columns} rows={result.rows} />
        </div>
      )}
    </div>
  );
}

function ResultTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  if (!rows.length) return <p className="muted">No rows matched.</p>;
  const numeric = columns.map((_, i) => rows.every((r) => r[i] == null || typeof r[i] === "number"));
  const show = (v: unknown) => v == null ? "" : typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)) : String(v);
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((c, i) => <th key={c + i} className={numeric[i] ? "num" : ""}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri}>{r.map((v, i) => <td key={i} className={numeric[i] ? "num" : ""}>{show(v)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
