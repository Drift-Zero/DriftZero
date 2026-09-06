import { orders, policySources, products, type Product } from '../data/catalog.ts';
import type { ScenarioId } from './demo-state.ts';

export type Citation = { id: string; label: string };
export type ConversationContext = { lastProductId?: string; lastOrderId?: string };
export type AssistantAnswer = {
  text: string;
  citations: Citation[];
  confidence: number;
  groundedness: number;
  unsupportedClaims: number;
  intent: string;
  suggestions: string[];
  context: ConversationContext;
};

const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const cite = (source: { id: string; title: string; version: string }): Citation => ({ id: source.id, label: `${source.title} ${source.version}` });

type Intent = 'order_lookup' | 'capabilities' | 'product_search' | 'inventory' | 'product_detail' | 'return_policy' | 'refund_policy' | 'warranty' | 'promotion' | 'shipping' | 'unsupported';

const commonTypos: Record<string, string> = {
  avalable: 'available',
  catlog: 'catalog',
  delvery: 'delivery',
  discout: 'discount',
  invetory: 'inventory',
  prcie: 'price',
  prodcut: 'product',
  prodcuts: 'products',
  refnd: 'refund',
  retrun: 'return',
  shiping: 'shipping',
  waranty: 'warranty',
  whats: "what's",
  whts: "what's",
};

function normalizeQuestion(question: string): string {
  return question
    .toLowerCase()
    .replace(/[’`]/g, "'")
    .replace(/[?!.,]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => commonTypos[word] ?? word)
    .join(' ');
}

function hasAny(query: string, phrases: string[]): boolean {
  return phrases.some((phrase) => query.includes(phrase));
}

function isCatalogRequest(query: string): boolean {
  return hasAny(query, ['recommend', 'show me', 'what products', 'which products', 'what items', 'what do you sell', 'product list', 'products list', 'list products', 'list items', 'browse products', 'browse catalog', 'show catalog', 'view catalog', 'your catalog', 'under $'])
    || /\b(?:give|send) me (?:the |a |your )?(?:product|item|catalog)/.test(query);
}

function classifyIntent(query: string): Intent {
  if (/\bdz-?\d{4}\b/i.test(query) || hasAny(query, ['track my order', 'track order', 'where is my order', 'order status'])) return 'order_lookup';
  if (/^(?:hello|hey|hi|hiya)\b/.test(query) || hasAny(query, ['what can you do', 'help me'])) return 'capabilities';
  if (hasAny(query, ['refund', 'money back'])) return 'refund_policy';
  if (hasAny(query, ['return', 'returnable', 'send it back', 'damaged'])) return 'return_policy';
  if (hasAny(query, ['warranty', 'guarantee', 'accidental', 'defect'])) return 'warranty';
  if (hasAny(query, ['promo', 'discount', 'coupon', 'sale code', 'save20'])) return 'promotion';
  if (hasAny(query, ['shipping', 'delivery', 'deliver', 'arrive'])) return 'shipping';
  if (hasAny(query, ['stock', 'available', 'availability', 'sold out', 'have any left'])) return 'inventory';
  if (isCatalogRequest(query)) return 'product_search';
  if (hasAny(query, ['price', 'cost', 'how much', 'tell me about', 'tell me more', 'more details', 'details', 'go for'])) return 'product_detail';
  return 'unsupported';
}

function canUsePreviousProduct(query: string, intent: Intent): boolean {
  if (/\b(it|its|them|they|this|that|one|ones)\b/.test(query)) return true;
  if (intent === 'product_detail' && /^(?:what(?:'s| is) (?:the )?price|how much|price|cost|tell me more|more details|details)\b/.test(query)) return true;
  if (intent === 'warranty' && /^(?:what(?:'s| is) (?:the )?warranty|warranty)\b/.test(query)) return true;
  if (intent === 'return_policy' && /^(?:can i return|is it returnable|return it)\b/.test(query)) return true;
  return false;
}

function findProduct(query: string, context: ConversationContext, intent: Intent): Product | undefined {
  const direct = products.find((product) => product.aliases.some((alias) => query.includes(alias)));
  if (direct) return direct;
  if (canUsePreviousProduct(query, intent) && context.lastProductId) {
    return products.find((product) => product.id === context.lastProductId);
  }
  return undefined;
}

function finish(partial: Omit<AssistantAnswer, 'context'>, context: ConversationContext, product?: Product): AssistantAnswer {
  return { ...partial, context: { ...context, lastProductId: product?.id ?? context.lastProductId } };
}

export function answerQuestion(question: string, scenario: ScenarioId, context: ConversationContext = {}): AssistantAnswer {
  const q = normalizeQuestion(question);
  const intent = classifyIntent(q);
  const product = findProduct(q, context, intent);
  const degraded = scenario !== 'healthy' && scenario !== 'recovered';
  const safe = { confidence: 97, groundedness: 98, unsupportedClaims: 0 };

  const orderId = q.match(/dz-?\d{4}/i)?.[0].toUpperCase().replace('DZ', 'DZ-').replace('--', '-');
  if (intent === 'order_lookup') {
    const resolvedId = orderId ?? context.lastOrderId;
    const order = orders.find((item) => item.id === resolvedId);
    if (!order) return finish({ text: 'I can track a demo order when you provide its ID. Try DZ-1042, DZ-2088, or DZ-3190.', citations: [], confidence: 100, groundedness: 100, unsupportedClaims: 0, intent: 'order_lookup', suggestions: ['Track DZ-2088', 'Track DZ-3190'] }, context);
    const item = products.find((entry) => entry.id === order.productId)!;
    return { text: `${order.id} contains the ${item.name}. It is ${order.status} and its expected delivery is ${order.expectedDelivery}.`, citations: [{ id: `order-${order.id}`, label: `Order ${order.id}` }], ...safe, intent: 'order_lookup', suggestions: [`Can I return the ${item.name}?`, `What is the warranty on it?`], context: { lastOrderId: order.id, lastProductId: item.id } };
  }

  if (intent === 'capabilities') {
    return finish({ text: 'I can help you compare products, check stock, track demo orders, and explain shipping, returns, refunds, warranties, and promotions.', citations: [], confidence: 100, groundedness: 100, unsupportedClaims: 0, intent: 'capabilities', suggestions: ['Recommend headphones under $200', 'Track DZ-2088', 'What is your return policy?'] }, context);
  }

  if (intent === 'product_search') {
    const wantsFullCatalog = hasAny(q, ['product list', 'products list', 'list products', 'list items', 'catalog', 'what do you sell']);
    let matches = wantsFullCatalog ? [...products] : products.filter((item) => item.stock > 0);
    const previousProduct = products.find((item) => item.id === context.lastProductId);
    if (q.includes('similar') && previousProduct) {
      matches = matches.filter((item) => item.category === previousProduct.category && item.id !== previousProduct.id);
    }
    const budget = Number(q.match(/(?:under|below|less than)\s*\$?(\d+)/)?.[1]);
    if (budget) matches = matches.filter((item) => item.price < budget);
    if (q.includes('electronic') || q.includes('headphone') || q.includes('tech')) matches = matches.filter((item) => item.category === 'electronics');
    if (q.includes('fitness') || q.includes('running')) matches = matches.filter((item) => item.category === 'fitness');
    const picks = wantsFullCatalog ? matches : matches.slice(0, 3);
    const resultLabel = wantsFullCatalog ? 'Here is the current product list' : 'Here are the best matches';
    return finish({ text: picks.length ? `${resultLabel}: ${picks.map((item) => `${item.name} (${money.format(item.price)}${item.stock ? '' : ', sold out'})`).join(', ')}.` : 'I could not find an in-stock product matching those filters.', citations: [cite(policySources.catalog)], ...safe, intent: 'product_search', suggestions: picks.slice(0, 3).map((item) => `Tell me about the ${item.name}`) }, context, wantsFullCatalog ? undefined : picks[0]);
  }

  if (intent === 'inventory') {
    if (!product) return finish({ text: 'Which product would you like me to check?', citations: [], confidence: 100, groundedness: 100, unsupportedClaims: 0, intent: 'inventory', suggestions: ['Is the Arc Mini Speaker in stock?', 'Is the Roam Daypack available?'] }, context);
    const wrong = scenario === 'inventory_mismatch' && product.stock === 0;
    return finish({ text: wrong ? `${product.name} is in stock with 14 units ready to ship.` : product.stock > 0 ? `${product.name} is in stock. There are ${product.stock} units available.` : `${product.name} is currently sold out.`, citations: [cite(policySources.catalog)], confidence: wrong ? 93 : 99, groundedness: wrong ? 45 : 99, unsupportedClaims: wrong ? 1 : 0, intent: 'inventory', suggestions: [`How much is the ${product.name}?`, `Can I return it?`] }, context, product);
  }

  if (intent === 'product_detail') {
    if (!product) return finish({ text: 'Tell me the product name and I’ll check the catalog.', citations: [], confidence: 100, groundedness: 100, unsupportedClaims: 0, intent: 'product_detail', suggestions: ['Tell me about Nova headphones', 'Tell me about the Halo lamp'] }, context);
    return finish({ text: `${product.name} costs ${money.format(product.price)}. ${product.description} ${product.stock > 0 ? `${product.stock} are currently in stock.` : 'It is currently sold out.'}`, citations: [cite(policySources.catalog)], ...safe, intent: 'product_detail', suggestions: [`Can I return the ${product.name}?`, `What is its warranty?`, 'Show me similar products'] }, context, product);
  }

  if (intent === 'return_policy' || intent === 'refund_policy') {
    const stale = scenario === 'stale_returns';
    const source = stale ? policySources.retiredReturns : policySources.returns;
    if (intent === 'refund_policy') {
      return finish({ text: stale ? 'Approved refunds reach the original payment method within two business days.' : 'Approved refunds return to the original payment method within 5–7 business days.', citations: [cite(source)], confidence: stale ? 91 : 99, groundedness: stale ? 49 : 99, unsupportedClaims: stale ? 1 : 0, intent: 'refund_policy', suggestions: ['Can I return a clearance item?', 'Track DZ-1042'] }, context, product);
    }
    if (product?.clearance || q.includes('clearance')) {
      return finish({ text: stale ? 'Clearance items can be returned within 30 days when unused.' : 'Clearance items are final sale unless they arrive damaged or defective.', citations: [cite(source)], confidence: stale ? 95 : 99, groundedness: stale ? 42 : 99, unsupportedClaims: stale ? 1 : 0, intent: 'return_policy', suggestions: ['How long do refunds take?', 'What if the item is damaged?'] }, context, product);
    }
    if (product?.category === 'electronics' || q.includes('electronic') || q.includes('headphone') || q.includes('smartwatch')) {
      return finish({ text: stale ? 'Electronics can be returned within 30 days when unused.' : 'Electronics can be returned within 14 days. Defective items remain covered by their warranty.', citations: [cite(source)], confidence: stale ? 96 : 99, groundedness: stale ? 39 : 99, unsupportedClaims: stale ? 1 : 0, intent: 'return_policy', suggestions: ['What does the warranty cover?', 'How long do refunds take?'] }, context, product);
    }
    return finish({ text: 'Most unused items can be returned within 30 days. Electronics have a 14-day window, and clearance items are final sale unless damaged or defective.', citations: [cite(policySources.returns)], ...safe, intent: 'return_policy', suggestions: ['Can I return headphones after 20 days?', 'Are clearance items refundable?'] }, context, product);
  }

  if (intent === 'warranty') {
    const stale = scenario === 'outdated_warranty';
    return finish({ text: stale ? 'Electronics include a two-year replacement warranty covering defects and accidental damage.' : 'Electronics include a 12-month manufacturer warranty for defects. Accidental damage is not covered.', citations: [cite(policySources.warranty)], confidence: stale ? 92 : 98, groundedness: stale ? 36 : 98, unsupportedClaims: stale ? 2 : 0, intent: 'warranty', suggestions: ['Can I return it instead?', 'What counts as a defect?'] }, context, product);
  }

  if (intent === 'promotion') {
    const expired = scenario === 'expired_promotion';
    return finish({ text: expired ? 'Use code SAVE20 for 20% off your order today.' : 'There are no store-wide promotion codes active today. Product-specific markdowns appear directly in the catalog.', citations: [cite(policySources.promotions)], confidence: expired ? 90 : 99, groundedness: expired ? 43 : 99, unsupportedClaims: expired ? 1 : 0, intent: 'promotion', suggestions: ['Show me products under $100', 'Are clearance items refundable?'] }, context, product);
  }

  if (intent === 'shipping') {
    const conflict = scenario === 'shipping_conflict';
    return finish({ text: conflict ? 'Standard shipping always arrives within two business days.' : 'Standard shipping usually takes 3–5 business days. Your order confirmation contains the specific estimate.', citations: [cite(policySources.shipping)], confidence: conflict ? 78 : 97, groundedness: conflict ? 52 : 98, unsupportedClaims: conflict ? 1 : 0, intent: 'shipping', suggestions: ['Track DZ-2088', 'Do you offer expedited shipping?'] }, context, product);
  }

  return finish({ text: 'I can’t verify that from the ShopAssist catalog or policy library. I can help with products, stock, orders, shipping, returns, refunds, warranties, and promotions.', citations: [], confidence: degraded ? 76 : 100, groundedness: 100, unsupportedClaims: 0, intent: 'unsupported', suggestions: ['What products are under $100?', 'Track DZ-2088', 'Explain the return policy'] }, context, product);
}
