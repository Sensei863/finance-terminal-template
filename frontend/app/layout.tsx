import type { Metadata } from "next";
import { Cormorant_Garamond, EB_Garamond, Montserrat } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "./theme-provider";
import { TopNav } from "../components/layout/TopNav";
import { AuthGuard } from "../components/layout/AuthGuard";

const cormorant = Cormorant_Garamond({
  weight: ["300", "400", "600"],
  subsets: ["latin"],
  variable: "--font-cormorant",
  display: "swap",
});

const ebGaramond = EB_Garamond({
  weight: ["400"],
  style: ["normal", "italic"],
  subsets: ["latin"],
  variable: "--font-eb-garamond",
  display: "swap",
});

const montserrat = Montserrat({
  weight: ["300", "400", "500", "600"],
  subsets: ["latin"],
  variable: "--font-montserrat",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Faraglioni & Aegis | Pro Quant Terminal",
  description: "Family Office Quantitative Terminal",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${cormorant.variable} ${ebGaramond.variable} ${montserrat.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-sans">
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem={false}
          disableTransitionOnChange
        >
          <AuthGuard>
            <TopNav />
            {children}
          </AuthGuard>
        </ThemeProvider>
      </body>
    </html>
  );
}
