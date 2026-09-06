'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ArrowUp, BookOpenText, Box, ChevronRight, CircleCheck, RotateCcw, Search, ShieldCheck, ShoppingBag, Sparkles } from 'lucide-react';

import { products } from '../data/catalog.ts';
import { answerQuestion, replaceLatestConversationAnswer, type AssistantAnswer, type ConversationContext } from '../lib/assistant.ts';
import { readScenario, type ScenarioId } from '../lib/demo-state.ts';
import type { TelemetryDelivery } from '../lib/telemetry.ts';
import { Button } from './ui/button';

type ChatMessage = { id: number; role: 'assistant' | 'user'; text: string; answer?: AssistantAnswer; provider?: string; tokens?: number };
type AIChatReply = { answer?: unknown; model?: unknown; status?: unknown; sources?: unknown; telemetry?: unknown; usage?: { totalTokens?: unknown } };
type ProviderSource = { id: string; label: string };

const initialSuggestions = [
  'Recommend headphones under $200',
  'Track order DZ-2088',
  'What is your return policy?',
  'Do you have any discounts?',
];

export function ShopChat() {
  const [scenario, setScenario] = useState<ScenarioId>('healthy');
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: 1, role: 'assistant', text: 'Hi! I can help you find products, track orders, and understand store policies. What can I help with today?' },
  ]);
  const [suggestions, setSuggestions] = useState(initialSuggestions);
  const [context, setContext] = useState<ConversationContext>({});
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const [delivery, setDelivery] = useState<TelemetryDelivery>('ready');
  const nextId = useRef(2);
  const requestVersion = useRef(0);
  const messageEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    queueMicrotask(() => setScenario(readScenario()));
    const update = () => setScenario(readScenario());
    window.addEventListener('storage', update);
    window.addEventListener('shopassist:scenario', update);
    return () => {
      window.removeEventListener('storage', update);
      window.removeEventListener('shopassist:scenario', update);
    };
  }, []);

  useEffect(() => {
    messageEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, typing]);

  function resetConversation() {
    requestVersion.current += 1;
    setMessages([{ id: nextId.current++, role: 'assistant', text: 'Conversation reset. What would you like help with?' }]);
    setSuggestions(initialSuggestions);
    setContext({});
    setInput('');
    setDelivery('ready');
  }

  async function requestPrimaryModel(question: string): Promise<{ answer: string; model: string; sources: ProviderSource[]; tokens?: number; telemetry: TelemetryDelivery }> {
    const history = messages.map((message) => ({ role: message.role, text: message.text }));
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: question, history, scenario }),
    });
    const payload = await response.json() as AIChatReply;
    if (!response.ok || typeof payload.answer !== 'string' || !payload.answer.trim()) {
      throw new Error('Gemini chat request failed');
    }
    return {
      answer: payload.answer.trim(),
      model: typeof payload.model === 'string' ? payload.model : 'AI provider',
      tokens: typeof payload.usage?.totalTokens === 'number' ? payload.usage.totalTokens : undefined,
      telemetry: payload.telemetry === 'sent' || payload.telemetry === 'error' ? payload.telemetry : 'buffered',
      sources: Array.isArray(payload.sources)
        ? payload.sources.filter((source): source is ProviderSource => Boolean(source) && typeof source === 'object' && 'id' in source && typeof source.id === 'string' && 'label' in source && typeof source.label === 'string')
        : [],
    };
  }

  function send(text: string) {
    const question = text.trim();
    if (!question || typing) return;
    const fallbackAnswer = answerQuestion(question, scenario, context);
    const activeRequest = ++requestVersion.current;
    setMessages((current) => [...current, { id: nextId.current++, role: 'user', text: question }]);
    setInput('');
    setTyping(true);
    void requestPrimaryModel(question).then((reply) => {
      if (activeRequest !== requestVersion.current) return;
      setMessages((current) => [...current, {
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
      }]);
      setSuggestions(fallbackAnswer.suggestions);
      setContext(replaceLatestConversationAnswer(fallbackAnswer.context, reply.answer));
      setTyping(false);
      setDelivery(reply.telemetry);
    }).catch(() => {
      if (activeRequest !== requestVersion.current) return;
      setMessages((current) => [...current, { id: nextId.current++, role: 'assistant', text: fallbackAnswer.text, answer: fallbackAnswer, provider: 'Local fallback' }]);
      setSuggestions(fallbackAnswer.suggestions);
      setContext(fallbackAnswer.context);
      setTyping(false);
      setDelivery('error');
    });
  }

  return (
    <main className="store-shell">
      <header className="store-topbar">
        <Link className="store-brand" href="/" aria-label="ShopAssist home">
          <span className="store-mark"><ShoppingBag size={19} /></span>
          <span><strong>ShopAssist</strong><small>Customer care</small></span>
        </Link>
        <div className="store-search" aria-hidden="true"><Search size={16} /><span>Search the store</span></div>
        <nav className="store-nav" aria-label="Utility navigation">
          <span className="service-online"><i /> Online</span>
          <Link href="/demo">Presenter console</Link>
        </nav>
      </header>

      <section className="customer-workspace">
        <aside className="catalog-rail">
          <div className="catalog-intro">
            <p className="eyebrow">Featured today</p>
            <h1>Find the right thing, faster.</h1>
            <p>Ask about products, delivery, returns, warranties, promotions, or a demo order.</p>
          </div>
          <div className="product-list">
            {products.slice(0, 5).map((product) => (
              <button key={product.id} className="product-card" onClick={() => send(`Tell me about the ${product.name}`)}>
                <span className={`product-glyph category-${product.category}`}><Box size={17} /></span>
                <span className="product-copy"><strong>{product.name}</strong><small>${product.price} · {product.stock ? `${product.stock} available` : 'Sold out'}</small></span>
                <ChevronRight size={15} />
              </button>
            ))}
          </div>
          <div className="trust-note"><ShieldCheck size={17} /><span><strong>Evidence-backed answers</strong><small>Policy sources are shown with every factual response.</small></span></div>
        </aside>

        <section className="customer-chat" aria-label="Chat with ShopAssist">
          <div className="chat-titlebar">
            <div><p className="eyebrow">Shopping assistant</p><h2>Ask ShopAssist</h2></div>
            <Button variant="ghost" size="sm" onClick={resetConversation}><RotateCcw size={15} />New chat</Button>
          </div>
          <div className="conversation" aria-live="polite">
            {messages.map((message) => (
              <article key={message.id} className={`chat-line ${message.role}`}>
                {message.role === 'assistant' && <span className="chat-avatar"><Sparkles size={16} /></span>}
                <div className="chat-content">
                  <small>{message.role === 'assistant' ? 'ShopAssist' : 'You'}</small>
                  <div className="chat-bubble"><p>{message.text}</p></div>
                  {message.answer?.citations.length ? (
                    <div className="source-row">
                      <BookOpenText size={14} />
                      {message.answer.citations.map((citation) => <span key={citation.id}>{citation.label}</span>)}
                      {message.answer.confidence > 0 ? <em>{message.answer.confidence}% confidence</em> : message.provider ? <em>{message.provider}{message.tokens ? ` · ${message.tokens.toLocaleString()} tokens` : ''}</em> : null}
                    </div>
                  ) : null}
                  {message.provider && !message.answer?.citations.length ? (
                    <div className="source-row"><Sparkles size={14} /><span>{message.provider}</span>{message.tokens ? <em>{message.tokens.toLocaleString()} tokens</em> : null}</div>
                  ) : null}
                </div>
              </article>
            ))}
            {typing && <div className="typing-row"><span className="chat-avatar"><Sparkles size={16} /></span><span className="typing-dots"><i /><i /><i /></span></div>}
            <div ref={messageEnd} />
          </div>
          <div className="chat-composer-area">
            <div className="prompt-row" aria-label="Suggested questions">
              {suggestions.slice(0, 4).map((suggestion) => <button key={suggestion} onClick={() => send(suggestion)}>{suggestion}</button>)}
            </div>
            <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); send(input); }}>
              <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask anything about products or your order…" aria-label="Message ShopAssist" />
              <Button type="submit" size="icon" disabled={!input.trim() || typing} aria-label="Send message"><ArrowUp size={18} /></Button>
            </form>
            <div className="composer-meta"><span>Try demo orders DZ-1042, DZ-2088, or DZ-3190</span><span className={`delivery-state ${delivery}`}><CircleCheck size={13} />Telemetry {delivery}</span></div>
          </div>
        </section>
      </section>
    </main>
  );
}
