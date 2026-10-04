import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ClaimShield AI · Evidence-led claim review",
  description: "Healthcare claim review with grounded evidence, NVIDIA hosted intelligence, and human oversight.",
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>{children}</body></html>;
}
