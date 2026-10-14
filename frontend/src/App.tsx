import { useEffect, useState } from "react";
import { api, type Meta } from "./api";
import Overview from "./components/Overview";
import QueryBar from "./components/QueryBar";
import CapacitySimulator from "./components/CapacitySimulator";
import ShiftReport from "./components/ShiftReport";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <header className="topbar">
        <div className="brand">
          Production Intelligence
          <small>Part movement, quality and capacity</small>
        </div>
        <nav>
          <a href="#overview">Overview</a>
          <a href="#work-projects">Work Projects</a>
        </nav>
        <div className="spacer" />
        {meta && <span className="pill">Data through {meta.latest_date} · synthetic</span>}
      </header>
      <main>
        {error && <div className="notice error">Could not reach the API: {error}</div>}
        {meta && (
          <>
            <section id="overview">
              <Overview lines={meta.lines} />
            </section>
            <section id="work-projects">
              <div className="section-head">
                <h2>Work Projects</h2>
                <p>
                  Three tools built on the same part-movement data: ask questions in plain English, test
                  staffing and downtime scenarios against the shift target, and hand off a shift report as a PDF.
                </p>
              </div>
              <QueryBar llmConfigured={meta.llm_configured} />
              <CapacitySimulator lines={meta.lines} />
              <ShiftReport meta={meta} />
            </section>
          </>
        )}
      </main>
    </>
  );
}
