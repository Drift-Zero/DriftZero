export type Product = {
  id: string;
  name: string;
  category: 'electronics' | 'apparel' | 'home' | 'fitness';
  price: number;
  stock: number;
  clearance?: boolean;
  aliases: string[];
  description: string;
};

export const products: Product[] = [
  {
    id: 'aero-buds',
    name: 'AeroBuds',
    category: 'electronics',
    price: 119,
    stock: 50,
    aliases: ['aerobuds', 'aero buds', 'earbuds'],
    description: 'Wireless earbuds with Bluetooth and an eight-hour battery.',
  },
  {
    id: 'nova-headphones',
    name: 'Nova ANC Headphones',
    category: 'electronics',
    price: 149,
    stock: 18,
    aliases: ['nova', 'headphone', 'headphones'],
    description:
      'Wireless over-ear headphones with adaptive noise cancellation.',
  },
  {
    id: 'pulse-watch',
    name: 'Pulse Smartwatch',
    category: 'electronics',
    price: 229,
    stock: 7,
    aliases: ['pulse', 'smartwatch', 'watch'],
    description: 'Fitness and sleep tracking with a seven-day battery.',
  },
  {
    id: 'arc-speaker',
    name: 'Arc Mini Speaker',
    category: 'electronics',
    price: 79,
    stock: 0,
    aliases: ['arc', 'speaker'],
    description: 'Portable waterproof speaker with room-filling sound.',
  },
  {
    id: 'loom-hoodie',
    name: 'Loom Everyday Hoodie',
    category: 'apparel',
    price: 64,
    stock: 31,
    aliases: ['loom', 'hoodie'],
    description: 'Midweight organic-cotton hoodie with a relaxed fit.',
  },
  {
    id: 'stride-runner',
    name: 'Stride Runner',
    category: 'fitness',
    price: 118,
    stock: 12,
    aliases: ['stride', 'runner', 'running shoe', 'shoes'],
    description: 'Responsive daily running shoe for road training.',
  },
  {
    id: 'terra-bottle',
    name: 'Terra Thermal Bottle',
    category: 'fitness',
    price: 32,
    stock: 42,
    aliases: ['terra', 'bottle'],
    description: 'Insulated stainless-steel bottle, 750 ml.',
  },
  {
    id: 'halo-lamp',
    name: 'Halo Desk Lamp',
    category: 'home',
    price: 54,
    stock: 9,
    aliases: ['halo', 'lamp'],
    description: 'Dimmable task lamp with adjustable color temperature.',
  },
  {
    id: 'nest-throw',
    name: 'Nest Woven Throw',
    category: 'home',
    price: 46,
    stock: 0,
    clearance: true,
    aliases: ['nest', 'throw', 'blanket'],
    description: 'Soft woven throw in a limited seasonal color.',
  },
  {
    id: 'roam-pack',
    name: 'Roam Daypack',
    category: 'apparel',
    price: 72,
    stock: 15,
    aliases: ['roam', 'daypack', 'backpack'],
    description: 'Weather-resistant 18 L backpack with laptop sleeve.',
  },
  {
    id: 'core-mat',
    name: 'Core Training Mat',
    category: 'fitness',
    price: 39,
    stock: 23,
    aliases: ['core', 'mat', 'yoga mat'],
    description: 'Cushioned, non-slip exercise mat.',
  },
  {
    id: 'drift-shirt',
    name: 'Drift Oxford Shirt',
    category: 'apparel',
    price: 58,
    stock: 11,
    aliases: ['drift', 'oxford', 'shirt'],
    description: 'Easy-care cotton shirt with a modern fit.',
  },
  {
    id: 'beam-charger',
    name: 'Beam 3-in-1 Charger',
    category: 'electronics',
    price: 89,
    stock: 5,
    aliases: ['beam', 'charger', 'charging'],
    description: 'Compact wireless dock for phone, watch, and earbuds.',
  },
];

export type Order = {
  id: string;
  productId: string;
  status: 'processing' | 'shipped' | 'delivered';
  placedOn: string;
  expectedDelivery: string;
};

export const orders: Order[] = [
  {
    id: 'DZ-1042',
    productId: 'nova-headphones',
    status: 'delivered',
    placedOn: '18 Aug 2026',
    expectedDelivery: '22 Aug 2026',
  },
  {
    id: 'DZ-2088',
    productId: 'roam-pack',
    status: 'shipped',
    placedOn: '2 Sep 2026',
    expectedDelivery: '8 Sep 2026',
  },
  {
    id: 'DZ-3190',
    productId: 'halo-lamp',
    status: 'processing',
    placedOn: '5 Sep 2026',
    expectedDelivery: '10 Sep 2026',
  },
];

export const policySources = {
  returns: {
    id: 'returns-policy-v2.1-current',
    title: 'Returns Policy',
    version: 'v2.1',
    updated: '4 Sep 2026',
  },
  retiredReturns: {
    id: 'returns-policy-v1.4-retired',
    title: 'Returns Policy',
    version: 'v1.4',
    updated: '12 Jan 2026',
  },
  warranty: {
    id: 'electronics-warranty-v3.0',
    title: 'Electronics Warranty',
    version: 'v3.0',
    updated: '28 Aug 2026',
  },
  shipping: {
    id: 'shipping-guide-v2.3',
    title: 'Shipping Guide',
    version: 'v2.3',
    updated: '1 Sep 2026',
  },
  shippingConflict: {
    id: 'shipping-guide-v1.9-conflicting',
    title: 'Shipping Guide',
    version: 'v1.9',
    updated: '15 Aug 2026',
  },
  promotions: {
    id: 'promotions-ledger-v5.2',
    title: 'Promotions Ledger',
    version: 'v5.2',
    updated: '6 Sep 2026',
  },
  promotionsRetired: {
    id: 'promotions-ledger-v4.8-retired',
    title: 'Promotions Ledger',
    version: 'v4.8 retired',
    updated: '10 Jul 2026',
  },
  catalog: {
    id: 'catalog-snapshot-2026-09-06',
    title: 'Product Catalog',
    version: '6 Sep snapshot',
    updated: '6 Sep 2026',
  },
};
