import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] });
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] });
const publicUrl = process.env.SHOPASSIST_PUBLIC_URL ?? 'http://localhost:3000';

export const metadata: Metadata = {
  metadataBase: new URL(publicUrl),
  title: 'ShopAssist · DriftZero Demo',
  description: 'A deterministic e-commerce support assistant for demonstrating AI reliability monitoring.',
  openGraph: {
    title: 'ShopAssist × DriftZero',
    description: 'Detect. Diagnose. Recover.',
    images: [{ url: '/shopassist-og.png', width: 1200, height: 630, alt: 'ShopAssist and DriftZero reliability demo' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'ShopAssist × DriftZero',
    description: 'Detect. Diagnose. Recover.',
    images: ['/shopassist-og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>{children}</body>
    </html>
  );
}
