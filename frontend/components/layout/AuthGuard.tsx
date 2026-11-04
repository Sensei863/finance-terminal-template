"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (pathname === "/login" || pathname.startsWith("/api") || pathname.includes(".")) {
      setIsAuthenticated(true);
      return;
    }

    let isMounted = true;
    fetch("/api/auth/check")
      .then((res) => res.json())
      .then((data) => {
        if (!isMounted) return;
        if (data.authenticated) {
          setIsAuthenticated(true);
        } else {
          setIsAuthenticated(false);
          router.push("/login");
        }
      })
      .catch(() => {
        if (!isMounted) return;
        setIsAuthenticated(false);
        router.push("/login");
      });

    return () => {
      isMounted = false;
    };
  }, [pathname, router]);

  if (isAuthenticated === null) {
    return <div className="min-h-screen bg-[var(--background)]" />; // blank flash protection
  }

  if (isAuthenticated === false && pathname !== "/login") {
    return <div className="min-h-screen bg-[var(--background)]" />; // don't render children while redirecting
  }

  return <>{children}</>;
}
