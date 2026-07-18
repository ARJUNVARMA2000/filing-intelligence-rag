"use client";

import { ArrowUpRight, BookOpenText, Database, FileText, X } from "lucide-react";
import { motion } from "motion/react";
import { citationHref, citationLocation } from "@/lib/research";
import type { Citation, HealthResponse } from "@/types/research";

interface EvidencePanelProps {
  citations: Citation[];
  activeSource: string | null;
  health: HealthResponse | null;
  onSelect: (sourceId: string) => void;
  onClose: () => void;
}

export function EvidencePanel({ citations, activeSource, health, onSelect, onClose }: EvidencePanelProps) {
  if (!citations.length) return <CoveragePanel health={health} />;

  return (
    <motion.aside
      className="evidence-panel"
      aria-label="Evidence inspector"
      initial={{ opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
    >
      <header className="evidence-header">
        <div>
          <span>Evidence margin</span>
          <strong>{String(citations.length).padStart(2, "0")} sources</strong>
        </div>
        <button type="button" onClick={onClose} aria-label="Close evidence inspector">
          <X size={17} aria-hidden="true" />
        </button>
      </header>

      <div className="source-list">
        {citations.map((citation, index) => {
          const sourceId = citation.source_id ?? `S${index + 1}`;
          const selected = sourceId === activeSource;
          const href = citationHref(citation);
          const relevance = citation.relevance_score == null
            ? null
            : Math.round(Math.max(0, Math.min(1, citation.relevance_score)) * 100);
          return (
            <article className={`source-card ${selected ? "is-active" : ""}`} key={`${citation.doc_id}-${citation.chunk_id ?? index}`}>
              <button className="source-card-main" type="button" onClick={() => onSelect(sourceId)}>
                <span className="source-number">{sourceId}</span>
                <span className="source-content">
                  <span className="source-kicker">
                    {citation.ticker?.toUpperCase() ?? "SOURCE"}
                    {citation.period ? ` · ${citation.period}` : ""}
                  </span>
                  <strong>{citation.doc_title ?? citation.filing_type ?? "Source document"}</strong>
                  <span className="source-location">{citationLocation(citation)}</span>
                </span>
                {relevance !== null && (
                  <span className="relevance"><strong>{relevance}%</strong><small>retrieval relevance</small></span>
                )}
              </button>

              {selected && (
                <motion.div className="source-detail" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}>
                  {citation.text && <blockquote>{citation.text}</blockquote>}
                  <div className="source-actions">
                    <span>{citation.filing_type ?? "Document"}</span>
                    {href && (
                      <a href={href} target="_blank" rel="noreferrer">
                        View cited page <ArrowUpRight size={14} aria-hidden="true" />
                      </a>
                    )}
                  </div>
                </motion.div>
              )}
            </article>
          );
        })}
      </div>
    </motion.aside>
  );
}

function CoveragePanel({ health }: { health: HealthResponse | null }) {
  const tickers = Object.keys(health?.data?.coverage ?? {});
  return (
    <aside className="coverage-panel" aria-label="Research coverage">
      <header>
        <span>Inside the index</span>
        <strong>Built for verification.</strong>
      </header>
      <p>Answers are assembled from ranked filing passages. The source trail stays attached all the way to the cited page.</p>
      <dl className="coverage-stats">
        <div><Database size={16} aria-hidden="true" /><dt>Indexed passages</dt><dd>{health?.indexChunks.toLocaleString() ?? "—"}</dd></div>
        <div><FileText size={16} aria-hidden="true" /><dt>Documents</dt><dd>{health?.data?.documents.toLocaleString() ?? "—"}</dd></div>
        <div><BookOpenText size={16} aria-hidden="true" /><dt>Companies</dt><dd>{tickers.length || "—"}</dd></div>
      </dl>
      {tickers.length > 0 && (
        <div className="ticker-tape" aria-label="Available companies">
          {tickers.slice(0, 15).map((ticker) => <span key={ticker}>{ticker}</span>)}
        </div>
      )}
      <ol className="method-list">
        <li><span>01</span><p><strong>Define the scope</strong>Company and reporting period</p></li>
        <li><span>02</span><p><strong>Rank the evidence</strong>Relevant source passages</p></li>
        <li><span>03</span><p><strong>Verify the answer</strong>Page and line references</p></li>
      </ol>
    </aside>
  );
}
