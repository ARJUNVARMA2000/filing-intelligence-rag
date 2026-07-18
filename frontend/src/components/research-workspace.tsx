"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowDown, CircleAlert, SearchCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { normalizePeriod, parseTickers } from "@/lib/research";
import type {
  ChatResponse,
  HealthResponse,
  ParseQueryResponse,
  ResearchMessage,
} from "@/types/research";
import { AnswerBrief } from "./answer-brief";
import { EvidencePanel } from "./evidence-panel";
import { ProductHeader } from "./product-header";
import { ResearchComposer } from "./research-composer";

const SAMPLE_QUESTIONS = [
  {
    tag: "Revenue",
    question: "How much revenue did Amazon report in Q3 2025, and what drove the change?",
  },
  {
    tag: "Margins",
    question: "Compare NVIDIA's gross margin commentary across Q2 and Q3 2026.",
  },
  {
    tag: "Risk",
    question: "What risks did Walmart management emphasize in its latest earnings call?",
  },
] as const;

const PROGRESS = [
  "Resolving company and reporting period",
  "Retrieving and ranking source evidence",
  "Drafting the evidence-grounded brief",
] as const;

async function readJson<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(payload.error ?? "The research service is unavailable.");
  return payload;
}

export function ResearchWorkspace() {
  const [messages, setMessages] = useState<ResearchMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [tickers, setTickers] = useState("");
  const [period, setPeriod] = useState("");
  const [topK, setTopK] = useState(8);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [evidenceMessageId, setEvidenceMessageId] = useState<string | null>(null);
  const [activeSource, setActiveSource] = useState<string | null>(null);
  const [showEvidence, setShowEvidence] = useState(true);
  const threadEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let current = true;
    fetch("/api/health", { cache: "no-store" })
      .then(async (response) => {
        const payload = (await response.json()) as HealthResponse;
        if (current) setHealth(payload);
      })
      .catch(() => current && setHealth({ ready: false, indexChunks: 0, data: null }));
    return () => { current = false; };
  }, []);

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => setProgress((value) => Math.min(value + 1, 2)), 2100);
    return () => window.clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const evidenceMessage = useMemo(
    () => messages.find((message) => message.id === evidenceMessageId) ?? [...messages].reverse().find((message) => message.role === "assistant"),
    [messages, evidenceMessageId],
  );

  const reset = useCallback(() => {
    setMessages([]);
    setQuestion("");
    setTickers("");
    setPeriod("");
    setError(null);
    setEvidenceMessageId(null);
    setActiveSource(null);
    setShowEvidence(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const submit = useCallback(async () => {
    const prompt = question.trim();
    if (!prompt || loading) return;

    const userMessage: ResearchMessage = { id: crypto.randomUUID(), role: "user", content: prompt };
    const priorMessages = [...messages];
    setMessages((current) => [...current, userMessage]);
    setQuestion("");
    setLoading(true);
    setProgress(0);
    setError(null);

    let parsed: ParseQueryResponse = { needs_clarification: false };
    try {
      parsed = await readJson<ParseQueryResponse>(
        await fetch("/api/parse-query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: prompt }),
        }),
      );
    } catch {
      parsed = {
        needs_clarification: true,
        clarification_message: "Automatic scope detection was unavailable; the selected scope was used.",
      };
    }

    const pinnedTickers = parseTickers(tickers);
    const resolvedTickers = pinnedTickers.length ? pinnedTickers : (parsed.tickers ?? []);
    const pinnedPeriod = period.trim() ? normalizePeriod(period) : "";
    const resolvedPeriod = pinnedPeriod || parsed.period || "";

    if (!pinnedTickers.length && parsed.tickers?.length) setTickers(parsed.tickers.join(", "));
    if (!pinnedPeriod && parsed.period) setPeriod(parsed.period.replace("-", " "));

    try {
      setProgress(1);
      const history = priorMessages
        .filter((message) => message.content)
        .slice(-8)
        .map(({ role, content }) => ({ role, content: content.slice(0, 2000) }));
      const data = await readJson<ChatResponse>(
        await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: prompt,
            tickers: resolvedTickers.length ? resolvedTickers : null,
            period: resolvedPeriod || null,
            top_k: topK,
            history,
          }),
        }),
      );
      if (!data.answer?.trim()) throw new Error("The research service returned an empty brief.");
      setProgress(2);
      const assistant: ResearchMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.answer,
        citations: data.citations ?? [],
        scope: { tickers: resolvedTickers, period: resolvedPeriod || undefined },
        clarification: parsed.needs_clarification ? parsed.clarification_message : null,
      };
      setMessages((current) => [...current, assistant]);
      setEvidenceMessageId(assistant.id);
      setActiveSource(data.citations?.[0]?.source_id ?? (data.citations?.length ? "S1" : null));
      setShowEvidence(true);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "The research request failed.");
    } finally {
      setLoading(false);
    }
  }, [loading, messages, period, question, tickers, topK]);

  function inspectCitation(messageId: string, sourceId: string) {
    setEvidenceMessageId(messageId);
    setActiveSource(sourceId);
    setShowEvidence(true);
    window.setTimeout(() => document.querySelector(".evidence-panel")?.scrollIntoView({ behavior: "smooth", block: "start" }), 20);
  }

  const hasThread = messages.length > 0;
  const assistantCount = messages.filter((message) => message.role === "assistant").length;

  return (
    <div className="site-shell" id="top">
      <ProductHeader ready={health?.ready ?? null} onReset={reset} hasThread={hasThread} />

      <main className={`workspace ${hasThread ? "has-thread" : ""}`}>
        <section className="research-column">
          {!hasThread ? (
            <motion.div className="landing" initial="hidden" animate="visible" variants={{ visible: { transition: { staggerChildren: 0.08 } } }}>
              <motion.div className="landing-kicker" variants={{ hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0 } }}>
                <span>Financial research / grounded</span>
                <span className="edition">2026 edition</span>
              </motion.div>
              <motion.div className="hero" variants={{ hidden: { opacity: 0, y: 18 }, visible: { opacity: 1, y: 0 } }}>
                <h1>Read between<br />the <em>filing lines.</em></h1>
                <p>Turn financial questions into concise, defensible briefs—each conclusion connected to the exact evidence behind it.</p>
              </motion.div>
              <motion.div variants={{ hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0 } }}>
                <ResearchComposer
                  question={question}
                  tickers={tickers}
                  period={period}
                  topK={topK}
                  loading={loading}
                  onQuestion={setQuestion}
                  onTickers={setTickers}
                  onPeriod={setPeriod}
                  onTopK={setTopK}
                  onSubmit={submit}
                />
              </motion.div>
              <motion.div className="prompt-starters" variants={{ hidden: { opacity: 0 }, visible: { opacity: 1 } }}>
                <div className="starter-label"><span>Or begin with a desk note</span><ArrowDown size={14} aria-hidden="true" /></div>
                <div className="starter-grid">
                  {SAMPLE_QUESTIONS.map((sample, index) => (
                    <button type="button" key={sample.tag} onClick={() => setQuestion(sample.question)}>
                      <span>{String(index + 1).padStart(2, "0")} / {sample.tag}</span>
                      <strong>{sample.question}</strong>
                      <i>Use this prompt</i>
                    </button>
                  ))}
                </div>
              </motion.div>
            </motion.div>
          ) : (
            <div className="thread">
              <header className="thread-header">
                <div><span>Active research</span><h1>Analysis desk</h1></div>
                <p>{tickers || "Auto-detected scope"}<br />{period || "Latest relevant period"} · {String(assistantCount).padStart(2, "0")} briefs</p>
              </header>

              <div className="thread-messages" aria-live="polite">
                {messages.map((message) => message.role === "user" ? (
                  <div className="research-question" key={message.id}>
                    <span>Research question</span>
                    <p>{message.content}</p>
                  </div>
                ) : (
                  <AnswerBrief
                    key={message.id}
                    message={message}
                    sequence={messages.filter((item) => item.role === "assistant" && messages.indexOf(item) <= messages.indexOf(message)).length}
                    onCitation={(sourceId) => inspectCitation(message.id, sourceId)}
                  />
                ))}

                <AnimatePresence>
                  {loading && (
                    <motion.div className="research-progress" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                      <div className="progress-orbit"><SearchCheck size={22} aria-hidden="true" /></div>
                      <div><span>Building the brief</span><strong>{PROGRESS[progress]}</strong></div>
                      <ol>{PROGRESS.map((step, index) => <li className={index <= progress ? "is-done" : ""} key={step}>{index < progress ? "Done" : index === progress ? "Now" : "Next"}</li>)}</ol>
                    </motion.div>
                  )}
                </AnimatePresence>

                {error && (
                  <div className="request-error" role="alert">
                    <CircleAlert size={19} aria-hidden="true" />
                    <div><strong>Research interrupted</strong><span>{error}</span></div>
                    <button type="button" onClick={() => setQuestion(messages.at(-1)?.role === "user" ? messages.at(-1)?.content ?? "" : "")}>Try again</button>
                  </div>
                )}
                <div ref={threadEnd} />
              </div>

              <div className="follow-up-composer">
                <ResearchComposer
                  compact
                  question={question}
                  tickers={tickers}
                  period={period}
                  topK={topK}
                  loading={loading}
                  onQuestion={setQuestion}
                  onTickers={setTickers}
                  onPeriod={setPeriod}
                  onTopK={setTopK}
                  onSubmit={submit}
                />
              </div>
            </div>
          )}
        </section>

        {showEvidence && (
          <EvidencePanel
            citations={evidenceMessage?.citations ?? []}
            activeSource={activeSource}
            health={health}
            onSelect={setActiveSource}
            onClose={() => setShowEvidence(false)}
          />
        )}
      </main>

      <footer className="site-footer">
        <span>Filing Intelligence</span>
        <p>Evidence-grounded analysis is a research aid, not investment advice.</p>
      </footer>
    </div>
  );
}
