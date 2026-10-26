import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NetSphere",
  description: "Enterprise Hybrid Multi-Cloud Network Management & Automation Platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans">{children}</body>
    </html>
  );
}
