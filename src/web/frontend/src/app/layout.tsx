import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Installer Dashboard — Zero-Touch Site Assessor",
  description: "Review and approve AI-generated solar + heat pump proposals",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
