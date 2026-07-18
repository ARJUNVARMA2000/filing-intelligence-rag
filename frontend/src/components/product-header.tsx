"use client";

import { Activity, RotateCcw } from "lucide-react";

interface ProductHeaderProps {
  ready: boolean | null;
  onReset: () => void;
  hasThread: boolean;
}

export function ProductHeader({ ready, onReset, hasThread }: ProductHeaderProps) {
  return (
    <header className="product-header">
      <a className="wordmark" href="#top" aria-label="Filing Intelligence home">
        <span className="wordmark-mark" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span>
          <strong>Filing Intelligence</strong>
          <small>Research, with receipts.</small>
        </span>
      </a>

      <div className="header-actions">
        <div className={`health-pill ${ready === false ? "is-offline" : ""}`} role="status">
          <Activity size={14} strokeWidth={1.8} aria-hidden="true" />
          {ready === null ? "Checking index" : ready ? "Evidence index ready" : "Service offline"}
        </div>
        {hasThread && (
          <button className="quiet-button" type="button" onClick={onReset}>
            <RotateCcw size={15} aria-hidden="true" />
            New research
          </button>
        )}
      </div>
    </header>
  );
}
