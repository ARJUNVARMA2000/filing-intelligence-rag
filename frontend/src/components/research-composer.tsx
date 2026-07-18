"use client";

import { ArrowUpRight, SlidersHorizontal } from "lucide-react";
import type { FormEvent } from "react";
import { validPeriod, validTickers } from "@/lib/research";

interface ResearchComposerProps {
  question: string;
  tickers: string;
  period: string;
  topK: number;
  loading: boolean;
  compact?: boolean;
  onQuestion: (value: string) => void;
  onTickers: (value: string) => void;
  onPeriod: (value: string) => void;
  onTopK: (value: number) => void;
  onSubmit: () => void;
}

export function ResearchComposer({
  question,
  tickers,
  period,
  topK,
  loading,
  compact = false,
  onQuestion,
  onTickers,
  onPeriod,
  onTopK,
  onSubmit,
}: ResearchComposerProps) {
  const tickersValid = validTickers(tickers);
  const periodValid = validPeriod(period);
  const canSubmit = question.trim().length > 0 && tickersValid && periodValid && !loading;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canSubmit) onSubmit();
  }

  return (
    <form className={`research-composer ${compact ? "is-compact" : ""}`} onSubmit={submit}>
      <label className="question-field">
        <span className="sr-only">Research question</span>
        <textarea
          value={question}
          onChange={(event) => onQuestion(event.target.value)}
          placeholder="Ask about revenue, margins, guidance, or risk…"
          rows={compact ? 2 : 3}
          maxLength={6000}
          disabled={loading}
        />
      </label>

      <div className="composer-controls">
        <div className="scope-fields">
          <label>
            <span>Companies</span>
            <input
              value={tickers}
              onChange={(event) => onTickers(event.target.value)}
              placeholder="Auto-detect or enter NVDA, AMZN"
              aria-invalid={!tickersValid}
              disabled={loading}
            />
            {!tickersValid && <small>Use up to 8 ticker symbols.</small>}
          </label>
          <label>
            <span>Reporting period</span>
            <input
              value={period}
              onChange={(event) => onPeriod(event.target.value)}
              placeholder="Auto-detect or enter Q3 2026"
              aria-invalid={!periodValid}
              disabled={loading}
            />
            {!periodValid && <small>Use Q3 2026, FY 2025, or LATEST.</small>}
          </label>
        </div>

        <div className="composer-submit-row">
          <details className="evidence-depth">
            <summary>
              <SlidersHorizontal size={14} aria-hidden="true" />
              Evidence depth · {topK}
            </summary>
            <div className="depth-popover">
              <label htmlFor="evidence-depth">Passages considered</label>
              <input
                id="evidence-depth"
                type="range"
                min="4"
                max="16"
                step="1"
                value={topK}
                onChange={(event) => onTopK(Number(event.target.value))}
              />
              <div><span>Focused</span><strong>{topK}</strong><span>Broad</span></div>
            </div>
          </details>
          <button className="submit-button" type="submit" disabled={!canSubmit}>
            {loading ? "Researching" : compact ? "Continue" : "Build the brief"}
            <ArrowUpRight size={17} strokeWidth={1.8} aria-hidden="true" />
          </button>
        </div>
      </div>
    </form>
  );
}
