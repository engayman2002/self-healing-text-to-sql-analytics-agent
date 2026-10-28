import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Self-Healing Text-to-SQL Analytics Agent",
  description:
    "Zero-trust, deterministic self-healing Text-to-SQL analytics platform powered by Groq and LangGraph.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark h-full">
      <body className="h-full bg-slate-950 text-slate-100 antialiased selection:bg-blue-600 selection:text-white">
        {children}
      </body>
    </html>
  );
}
