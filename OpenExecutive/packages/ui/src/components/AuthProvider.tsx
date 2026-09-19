"use client";

import { SessionProvider } from "next-auth/react";
import type { ReactNode } from "react";

// Thin client wrapper around NextAuth's SessionProvider so server-side
// layouts can hand off a client-side session context. Required for
// `useSession()` hook calls anywhere in the tree.
export default function AuthProvider({ children }: { children: ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
