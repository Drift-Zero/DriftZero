'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowUp,
  ArrowUpRight,
  BookOpenText,
  Box,
  ChevronRight,
  CircleCheck,
  RotateCcw,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
} from 'lucide-react';

import { products } from '../data/catalog.ts';
import {
  answerQuestion,
  replaceLatestConversationAnswer,
  type AssistantAnswer,
  type ConversationContext,
} from '../lib/assistant.ts';
import { readScenarios, type ScenarioId } from '../lib/demo-state.ts';
import {
  buildDetectionReport,
  writeDetectionReport,
  type DetectionReport,
} from '../lib/detection.ts';
import type { TelemetryDelivery } from '../lib/telemetry.ts';
import { Button } from './ui/button';

type ChatMessage = {
  id: number;
  role: 'assistant' | 'user';
  text: string;
  answer?: AssistantAnswer;
  provider?: string;
  tokens?: number;
};
type AIChatReply = {
  answer?: unknown;
  model?: unknown;
  status?: unknown;
  sources?: unknown;
  telemetry?: unknown;
  detection?: unknown;
  usage?: { totalTokens?: unknown };
};
type ProviderSource = { id: string; label: string };

const initialSuggestions = [
  'Recommend headphones under $200',
  'Track order DZ-2088',
  'What is your return policy?',
  'Do you have any discounts?',
];

export function ShopChat() {
  const [scenarios, setScenarios] = useState<ScenarioId[]>(['healthy']);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 1,
      role: 'assistant',
      text: 'Hi! I can help you find products, track orders, and understand store policies. What can I help with today?',
    },
  ]);
  const [suggestions, setSuggestions] = useState(initialSuggestions);
  const [context, setContext] = useState<ConversationContext>({});
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const [delivery, setDelivery] = useState<TelemetryDelivery>('ready');
  const nextId = useRef(2);
  const requestVersion = useRef(0);
  const conversation = useRef<HTMLDivElement>(null);

  useEffect(() => {
    queueMicrotask(() => setScenarios(readScenarios()));
    const update = () => setScenarios(readScenarios());
    window.addEventListener('storage', update);
    window.addEventListener('shopassist:scenario', update);
    return () => {
      window.removeEventListener('storage', update);
      window.removeEventListener('shopassist:scenario', update);
    };
  }, []);

  useEffect(() => {
    conversation.current?.scrollTo({
      top: conversation.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, typing]);

  function resetConversation() {
    requestVersion.current += 1;
    setMessages([
      {
        id: nextId.current++,
        role: 'assistant',
        text: 'Conversation reset. What would you like help with?',
      },
    ]);
    setSuggestions(initialSuggestions);
    setContext({});
    setInput('');
    setDelivery('ready');
  }

  async function requestPrimaryModel(question: string): Promise<{
    answer: string;
    model: string;
    sources: ProviderSource[];
    tokens?: number;
    telemetry: TelemetryDelivery;
    detection: DetectionReport | null;
  }> {
    const history = messages.map((message) => ({
      role: message.role,
      text: message.text,
    }));
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: question, history, scenarios }),
    });
    const payload = (await response.json()) as AIChatReply;
    if (
      !response.ok ||
      typeof payload.answer !== 'string' ||
      !payload.answer.trim()
    ) {
      throw new Error('Groq chat request failed');
    }
    return {
      answer: payload.answer.trim(),
      model: typeof payload.model === 'string' ? payload.model : 'AI provider',
      tokens:
        typeof payload.usage?.totalTokens === 'number'
          ? payload.usage.totalTokens
          : undefined,
      telemetry:
        payload.telemetry === 'sent' || payload.telemetry === 'error'
          ? payload.telemetry
          : 'buffered',
      detection:
        payload.detection && typeof payload.detection === 'object'
          ? (payload.detection as DetectionReport)
          : null,
      sources: Array.isArray(payload.sources)
        ? payload.sources.filter(
            (source): source is ProviderSource =>
              Boolean(source) &&
              typeof source === 'object' &&
              'id' in source &&
              typeof source.id === 'string' &&
              'label' in source &&
              typeof source.label === 'string',
          )
        : [],
    };
  }

  function send(text: string) {
    const question = text.trim();
    if (!question || typing) return;
    const fallbackAnswer = answerQuestion(question, scenarios, context);
    const activeRequest = ++requestVersion.current;
    setMessages((current) => [
      ...current,
      { id: nextId.current++, role: 'user', text: question },
    ]);
    setInput('');
    setTyping(true);
    void requestPrimaryModel(question)
      .then((reply) => {
        if (activeRequest !== requestVersion.current) return;
        setMessages((current) => [
          ...current,
          {
            id: nextId.current++,
            role: 'assistant',
            text: reply.answer,
            provider: reply.model,
            tokens: reply.tokens,
            answer: {
              ...fallbackAnswer,
              text: reply.answer,
              citations: reply.sources,
              confidence: 0,
              groundedness: 0,
              unsupportedClaims: 0,
              intent: 'gemini_grounded_chat',
            },
          },
        ]);
        setSuggestions(fallbackAnswer.suggestions);
        setContext(
          replaceLatestConversationAnswer(fallbackAnswer.context, reply.answer),
        );
        setTyping(false);
        setDelivery(reply.telemetry);
        if (reply.detection) writeDetectionReport(reply.detection);
      })
      .catch(() => {
        if (activeRequest !== requestVersion.current) return;
        setMessages((current) => [
          ...current,
          {
            id: nextId.current++,
            role: 'assistant',
            text: fallbackAnswer.text,
            answer: fallbackAnswer,
            provider: 'Local fallback',
          },
        ]);
        setSuggestions(fallbackAnswer.suggestions);
        setContext(fallbackAnswer.context);
        setTyping(false);
        setDelivery('error');
        writeDetectionReport(
          buildDetectionReport({
            question,
            answer: fallbackAnswer.text,
            citations: fallbackAnswer.citations.map((citation) => citation.id),
            scenarios,
            history: messages.map((message) => ({
              role: message.role,
              text: message.text,
            })),
          }),
        );
      });
  }

  return (
    <main className="store-shell">
      <header className="store-topbar">
        <Link className="store-brand" href="/" aria-label="ShopAssist home">
          <span className="store-mark">
            <ShoppingBag size={19} />
          </span>
          <span>
            <strong>ShopAssist</strong>
            <small>Personal shopping desk</small>
          </span>
        </Link>
        <nav className="store-nav" aria-label="Utility navigation">
          <Link className="presenter-link" href="/demo">
            <span className="nav-link-label">Presenter console</span>
            <ArrowUpRight size={14} />
          </Link>
        </nav>
      </header>

      <section className="customer-workspace">
        <aside className="catalog-rail">
          <div className="catalog-intro">
            <div className="intro-badge">
              <Sparkles size={13} /> Curated for you
            </div>
            <p className="eyebrow">Your shortcut to better picks</p>
            <h1>Find the right thing, faster.</h1>
            <p>
              Ask about products, delivery, returns, warranties, promotions, or
              a demo order.
            </p>
          </div>
          <div className="rail-heading">
            <span>Popular picks</span>
            <small>12 in catalog</small>
          </div>
          <div className="product-list">
            {products.slice(0, 5).map((product) => (
              <button
                key={product.id}
                className="product-card"
                onClick={() => send(`Tell me about the ${product.name}`)}
              >
                <span className={`product-glyph category-${product.category}`}>
                  <Box size={17} />
                </span>
                <span className="product-copy">
                  <strong>{product.name}</strong>
                  <small>
                    ${product.price} ·{' '}
                    {product.stock ? `${product.stock} available` : 'Sold out'}
                  </small>
                </span>
                <ChevronRight size={15} />
              </button>
            ))}
          </div>
          <div className="trust-note">
            <span className="trust-icon">
              <ShieldCheck size={17} />
            </span>
            <span>
              <strong>Evidence-backed answers</strong>
              <small>
                Policy sources are shown with every factual response.
              </small>
            </span>
          </div>
          <div className="catalog-status">
            <span>
              <i /> Catalog synced
            </span>
            <small>06 Sep 2026</small>
          </div>
        </aside>

        <section className="customer-chat" aria-label="Chat with ShopAssist">
          <div className="chat-titlebar">
            <div className="chat-identity">
              <span className="chat-title-avatar">
                <Sparkles size={17} />
              </span>
              <div className="chat-title-copy">
                <h2>Ask ShopAssist</h2>
                <span className="chat-status">
                  <i /> Ready
                </span>
              </div>
            </div>
            <div className="title-actions">
              <span className="source-status">
                <ShieldCheck size={13} /> Sources on
              </span>
              <Button variant="ghost" size="sm" onClick={resetConversation}>
                <RotateCcw size={15} />
                New chat
              </Button>
            </div>
          </div>
          <div ref={conversation} className="conversation" aria-live="polite">
            {messages.map((message) => (
              <article
                key={message.id}
                className={`chat-line ${message.role}`}
                aria-label={`${message.role} message`}
              >
                {message.role === 'assistant' && (
                  <span className="chat-avatar">
                    <Sparkles size={16} />
                  </span>
                )}
                <div className="chat-content">
                  {message.role === 'assistant' && <small>ShopAssist</small>}
                  <div className="chat-bubble">
                    <p>{message.text}</p>
                  </div>
                  {message.answer?.citations.length ? (
                    <div className="source-row">
                      <BookOpenText size={14} />
                      {message.answer.citations.map((citation) => (
                        <span key={citation.id}>{citation.label}</span>
                      ))}
                      {message.answer.confidence > 0 ? (
                        <em>{message.answer.confidence}% confidence</em>
                      ) : message.provider ? (
                        <em>
                          {message.provider}
                          {message.tokens
                            ? ` · ${message.tokens.toLocaleString()} tokens`
                            : ''}
                        </em>
                      ) : null}
                    </div>
                  ) : null}
                  {message.provider && !message.answer?.citations.length ? (
                    <div className="source-row">
                      <Sparkles size={14} />
                      <span>{message.provider}</span>
                      {message.tokens ? (
                        <em>{message.tokens.toLocaleString()} tokens</em>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </article>
            ))}
            {typing && (
              <div className="typing-row">
                <span className="chat-avatar">
                  <Sparkles size={16} />
                </span>
                <span className="typing-dots">
                  <i />
                  <i />
                  <i />
                </span>
              </div>
            )}
          </div>
          <div className="chat-composer-area">
            <div className="suggestion-strip">
              <span className="suggestion-label">Try asking</span>
              <div className="prompt-row" aria-label="Suggested questions">
                {suggestions.slice(0, 4).map((suggestion) => (
                  <button key={suggestion} onClick={() => send(suggestion)}>
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
            <form
              className="chat-composer"
              onSubmit={(event) => {
                event.preventDefault();
                send(input);
              }}
            >
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask about a product, order, or policy…"
                aria-label="Message ShopAssist"
              />
              <Button
                type="submit"
                size="icon"
                disabled={!input.trim() || typing}
                aria-label="Send message"
              >
                <ArrowUp size={18} />
              </Button>
            </form>
            <div className="composer-meta">
              <span>Try demo orders DZ-1042, DZ-2088, or DZ-3190</span>
              <span className={`delivery-state ${delivery}`}>
                <CircleCheck size={13} />
                Telemetry {delivery}
              </span>
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}
