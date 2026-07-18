import type { Citation } from "@/types/research";

const TICKER = /^[A-Z][A-Z0-9.-]{0,9}$/;
const PERIOD = /^(?:(?:Q[1-4]|FY)-\d{4}|LATEST)$/;

export function parseTickers(value: string): string[] {
  return [...new Set(value.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean))];
}

export function validTickers(value: string): boolean {
  const tickers = parseTickers(value);
  return tickers.length <= 8 && tickers.every((ticker) => TICKER.test(ticker));
}

export function normalizePeriod(value: string): string {
  return value.trim().toUpperCase().replace(/\s+/g, "-");
}

export function validPeriod(value: string): boolean {
  return !value.trim() || PERIOD.test(normalizePeriod(value));
}

export function citationLocation(citation: Citation): string {
  const parts: string[] = [];
  if (citation.page) parts.push(`Page ${citation.page}`);
  if (citation.line_start && citation.line_end) {
    parts.push(`Lines ${citation.line_start}–${citation.line_end}`);
  } else if (citation.line_start) {
    parts.push(`Line ${citation.line_start}`);
  }
  return parts.join(" · ") || "Location unavailable";
}

export function citationHref(citation: Citation): string | null {
  if (citation.highlight_url) {
    if (/^https?:\/\//.test(citation.highlight_url)) return citation.highlight_url;
    return `/api/source?path=${encodeURIComponent(citation.highlight_url)}`;
  }
  return citation.source_url ?? null;
}
