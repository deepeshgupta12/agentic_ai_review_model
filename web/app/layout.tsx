import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Noto_Sans_Devanagari } from "next/font/google";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const jetbrains = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });
const devanagari = Noto_Sans_Devanagari({ variable: "--font-devanagari", subsets: ["devanagari"], preload: false });

export const metadata: Metadata = {
  title: { default: "Project Intelligence", template: "%s · Project Intelligence" },
  description: "Evidence-linked project insights compiled by the client.",
  // POC: nothing is indexed until the product owner decides otherwise (I14).
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" className={`${inter.variable} ${jetbrains.variable} ${devanagari.variable}`}>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
