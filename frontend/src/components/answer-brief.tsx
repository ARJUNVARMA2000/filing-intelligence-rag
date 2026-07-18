"use client";

import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ResearchMessage } from "@/types/research";

interface AnswerBriefProps {
  message: ResearchMessage;
  sequence: number;
  onCitation: (sourceId: string) => void;
}

function citationNodes(children: ReactNode, onCitation: (sourceId: string) => void): ReactNode {
  if (Array.isArray(children)) return children.map((child) => citationNodes(child, onCitation));
  if (typeof children !== "string") return children;
  const chunks = children.split(/(\[S\d+\])/g);
  return chunks.map((chunk, index) => {
    const match = chunk.match(/^\[(S\d+)\]$/);
    return match ? (
      <button
        className="inline-citation"
        type="button"
        onClick={() => onCitation(match[1])}
        aria-label={`Inspect source ${match[1].slice(1)}`}
        key={`${chunk}-${index}`}
      >
        {match[1]}
      </button>
    ) : (
      chunk
    );
  });
}

export function AnswerBrief({ message, sequence, onCitation }: AnswerBriefProps) {
  return (
    <article className="answer-brief">
      <header className="brief-header">
        <div>
          <span>Research brief</span>
          <strong>{String(sequence).padStart(2, "0")}</strong>
        </div>
        <div className="brief-scope">
          {message.scope?.tickers.map((ticker) => <span key={ticker}>{ticker}</span>)}
          {message.scope?.period && <span>{message.scope.period}</span>}
        </div>
      </header>

      {message.clarification && (
        <aside className="scope-note">
          <strong>Scope note</strong>
          <span>{message.clarification}</span>
        </aside>
      )}

      <div className="answer-prose">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: ({ children }) => <p>{citationNodes(children, onCitation)}</p>,
            li: ({ children }) => <li>{citationNodes(children, onCitation)}</li>,
            a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
          }}
        >
          {message.content}
        </ReactMarkdown>
      </div>

      <footer className="brief-footer">
        <span>{message.citations?.length ?? 0} cited sources</span>
        <span>Verify material conclusions against the evidence margin.</span>
      </footer>
    </article>
  );
}
