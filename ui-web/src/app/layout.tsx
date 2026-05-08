import type { Metadata } from "next";
import "./globals.css";
import { Topbar } from "@/components/layout/Topbar";
import { Footer } from "@/components/layout/Footer";

export const metadata: Metadata = {
  title: "MedVerify · Evidence-checked medical claims",
  description:
    "Check medical statements for clinical accuracy. Get a clear verdict, the supporting evidence, and the relationships behind it.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link
          rel="preconnect"
          href="https://fonts.googleapis.com"
          crossOrigin=""
        />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600;8..60,700&display=swap"
        />
      </head>
      <body className="font-sans">
        <Topbar />
        <main className="mx-auto max-w-5xl px-6 py-14">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
