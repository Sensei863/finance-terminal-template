"use client";

import React, { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Moon, Sun, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function TopNav() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    setMounted(true);
  }, []);

  // Close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [pathname]);

  const navLinks = [
    { name: "Market Screener", path: "/screener-base" }, // base path just for tracking
    { name: "Portfolio Analysis", path: "/portfolio" },
    { name: "Newsletter", path: "/newsletter" },
    { name: "Settings", path: "/settings" },
  ];

  const NavItemContent = ({ link, isActive }: { link: any, isActive: boolean }) => {
    if (link.name === "Market Screener") {
      return (
        <div 
          className="relative group h-full flex flex-col md:flex-row md:items-center w-full"
          onMouseEnter={() => setOpenDropdown(link.name)}
          onMouseLeave={() => setOpenDropdown(null)}
        >
          <Link 
            href="/performance"
            onClick={(e) => {
              if (window.innerWidth < 768 && openDropdown !== link.name) {
                e.preventDefault();
                setOpenDropdown(link.name);
              }
            }}
            className={`flex items-center md:h-full md:border-b-2 px-4 py-3 md:px-2 md:py-0 transition-colors w-full touch-target ${
              isActive 
                ? "md:border-brand-gold text-brand-gold md:text-[var(--foreground)] bg-[var(--border-color)]/20 md:bg-transparent" 
                : "border-transparent text-brand-slate hover:text-[var(--foreground)]"
            }`}
          >
            {link.name}
          </Link>
          <div className={`
            md:absolute md:top-full md:left-0 md:mt-0 md:w-48 md:bg-[var(--background)] md:border md:border-[var(--border-color)] md:shadow-xl 
            ${openDropdown === link.name ? 'flex' : 'hidden'} md:group-hover:flex flex-col py-2 z-50
            pl-8 md:pl-0 border-l-2 border-[var(--border-color)]/30 ml-4 md:ml-0 md:border-l-0
          `}>
            <Link href="/performance" onClick={() => setOpenDropdown(null)} className="px-4 py-2 hover:bg-[var(--hover-bg)] hover:text-brand-gold transition-colors touch-target flex items-center">
              Performance & PnL
            </Link>
            <Link href="/technicals" onClick={() => setOpenDropdown(null)} className="px-4 py-2 hover:bg-[var(--hover-bg)] hover:text-brand-gold transition-colors touch-target flex items-center">
              Technical Analysis
            </Link>
          </div>
        </div>
      );
    }

    if (link.name === "Portfolio Analysis") {
      return (
        <div 
          className="relative group h-full flex flex-col md:flex-row md:items-center w-full"
          onMouseEnter={() => setOpenDropdown(link.name)}
          onMouseLeave={() => setOpenDropdown(null)}
        >
          <Link 
            href={link.path}
            onClick={(e) => {
              if (window.innerWidth < 768 && openDropdown !== link.name) {
                e.preventDefault();
                setOpenDropdown(link.name);
              }
            }}
            className={`flex items-center md:h-full md:border-b-2 px-4 py-3 md:px-2 md:py-0 transition-colors w-full touch-target ${
              isActive 
                ? "md:border-brand-gold text-brand-gold md:text-[var(--foreground)] bg-[var(--border-color)]/20 md:bg-transparent" 
                : "border-transparent text-brand-slate hover:text-[var(--foreground)]"
            }`}
          >
            {link.name}
          </Link>
          <div className={`
            md:absolute md:top-full md:left-0 md:mt-0 md:w-48 md:bg-[var(--background)] md:border md:border-[var(--border-color)] md:shadow-xl 
            ${openDropdown === link.name ? 'flex' : 'hidden'} md:group-hover:flex flex-col py-2 z-50
            pl-8 md:pl-0 border-l-2 border-[var(--border-color)]/30 ml-4 md:ml-0 md:border-l-0
          `}>
            <Link href="/portfolio?mode=dashboard" onClick={() => setOpenDropdown(null)} className="px-4 py-2 hover:bg-[var(--hover-bg)] hover:text-brand-gold transition-colors touch-target flex items-center">
              Dashboard
            </Link>
            <Link href="/portfolio?mode=performance" onClick={() => setOpenDropdown(null)} className="px-4 py-2 hover:bg-[var(--hover-bg)] hover:text-brand-gold transition-colors touch-target flex items-center">
              Performance Report
            </Link>
            <Link href="/portfolio?mode=ingestion" onClick={() => setOpenDropdown(null)} className="px-4 py-2 hover:bg-[var(--hover-bg)] hover:text-brand-gold transition-colors touch-target flex items-center">
              Trade Ingestion
            </Link>
            <Link href="/portfolio?mode=lookthrough" onClick={() => setOpenDropdown(null)} className="px-4 py-2 hover:bg-[var(--hover-bg)] hover:text-brand-gold transition-colors touch-target flex items-center">
              Look-Through
            </Link>
            <Link href="/portfolio?mode=optimization" onClick={() => setOpenDropdown(null)} className="px-4 py-2 hover:bg-[var(--hover-bg)] hover:text-brand-gold transition-colors touch-target flex items-center">
              Optimization
            </Link>
            <Link href="/portfolio?mode=factors" onClick={() => setOpenDropdown(null)} className="px-4 py-2 hover:bg-[var(--hover-bg)] hover:text-brand-gold transition-colors touch-target flex items-center">
              Factor Analysis
            </Link>
          </div>
        </div>
      );
    }

    return (
      <Link 
        href={link.path}
        onClick={() => setMobileMenuOpen(false)}
        className={`flex items-center md:h-full md:border-b-2 px-4 py-3 md:px-2 md:py-0 transition-colors w-full touch-target ${
          isActive 
            ? "md:border-brand-gold text-brand-gold md:text-[var(--foreground)] bg-[var(--border-color)]/20 md:bg-transparent" 
            : "border-transparent text-brand-slate hover:text-[var(--foreground)]"
        }`}
      >
        {link.name}
      </Link>
    );
  };

  return (
    <header className="h-16 border-b-2 border-brand-gold flex items-center justify-between px-4 md:px-6 bg-[var(--background)] shrink-0 z-50 relative">
      <div className="flex items-center gap-12 h-full">
        {/* Logo & Brand */}
        <Link href="/" className="flex items-center gap-3 md:gap-4 h-full touch-target">
          <img 
            src="https://raw.githubusercontent.com/Sensei863/faraglioni-assets/main/Logo.png" 
            alt="Faraglioni & Aegis Logo" 
            className="h-10 md:h-12 w-auto object-contain"
          />
          <div className="hidden sm:block">
            <h1 className="font-serif text-brand-gold font-semibold tracking-[0.3em] uppercase text-[10px] mb-1">
              Faraglioni & Aegis
            </h1>
            <div className="font-serif text-lg md:text-xl text-[var(--foreground)] font-light leading-none">
              Pro Quant <em className="text-brand-gold-light italic">Terminal</em>
            </div>
          </div>
        </Link>
        
        {/* Desktop Nav */}
        <nav className="hidden md:flex items-center gap-8 font-sans text-sm tracking-wide font-medium h-full">
          {navLinks.map((link) => {
            const isMarketScreenerActive = link.name === "Market Screener" && (pathname.startsWith("/performance") || pathname.startsWith("/technicals"));
            const isActive = isMarketScreenerActive || pathname.startsWith(link.path);
            return <NavItemContent key={link.name} link={link} isActive={isActive} />;
          })}
        </nav>
      </div>

      {/* Utilities */}
      <div className="flex items-center gap-2 md:gap-4 h-full">
        <div className="hidden sm:block text-[10px] uppercase tracking-widest text-brand-slate font-semibold px-4 border-r border-[var(--border-color)]">
          Status: <span className="text-brand-green">Connected</span>
        </div>
        {mounted && (
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="p-2 hover:bg-[var(--border-color)] transition-colors border border-transparent hover:border-[var(--border-color)] touch-target rounded"
            aria-label="Toggle Dark Mode"
          >
            {theme === "dark" ? (
              <Sun className="w-4 h-4 md:w-4 md:h-4 text-brand-gold-light" />
            ) : (
              <Moon className="w-4 h-4 md:w-4 md:h-4 text-brand-navy-light" />
            )}
          </button>
        )}
        
        {/* Mobile Menu Toggle */}
        <button 
          className="md:hidden p-2 text-[var(--foreground)] touch-target rounded border border-transparent hover:border-[var(--border-color)]"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {/* Mobile Nav Drawer */}
      {mobileMenuOpen && (
        <div className="absolute top-full left-0 w-full bg-[var(--background)] border-b border-[var(--border-color)] shadow-2xl flex flex-col md:hidden z-50">
          <nav className="flex flex-col font-sans text-sm tracking-wide font-medium">
            {navLinks.map((link) => {
              const isMarketScreenerActive = link.name === "Market Screener" && (pathname.startsWith("/performance") || pathname.startsWith("/technicals"));
              const isActive = isMarketScreenerActive || pathname.startsWith(link.path);
              return <NavItemContent key={link.name} link={link} isActive={isActive} />;
            })}
          </nav>
          <div className="p-4 border-t border-[var(--border-color)] text-[10px] uppercase tracking-widest text-brand-slate font-semibold">
            Status: <span className="text-brand-green">Connected</span>
          </div>
        </div>
      )}
    </header>
  );
}
