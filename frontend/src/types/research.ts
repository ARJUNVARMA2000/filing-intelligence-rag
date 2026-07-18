export type ChatRole = "user" | "assistant";

export interface ChatHistoryMessage {
  role: ChatRole;
  content: string;
}

export interface Citation {
  source_id?: string | null;
  doc_id: string;
  doc_title?: string | null;
  ticker?: string | null;
  filing_type?: string | null;
  period?: string | null;
  section?: string | null;
  page?: number | null;
  line_start?: number | null;
  line_end?: number | null;
  table_id?: string | null;
  source_url?: string | null;
  chunk_id?: string | null;
  highlight_url?: string | null;
  text?: string | null;
  relevance_score?: number | null;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  model?: string | null;
}

export interface ParseQueryResponse {
  tickers?: string[] | null;
  period?: string | null;
  needs_clarification: boolean;
  clarification_message?: string | null;
}

export interface ResearchMessage extends ChatHistoryMessage {
  id: string;
  citations?: Citation[];
  scope?: {
    tickers: string[];
    period?: string;
  };
  clarification?: string | null;
}

export interface DataHealth {
  status: string;
  documents: number;
  chunks: number;
  sources: string[];
  coverage: Record<string, string[]>;
  freshness?: {
    status?: string;
    latest_fetch?: string | null;
  };
}

export interface HealthResponse {
  ready: boolean;
  indexChunks: number;
  data: DataHealth | null;
}
