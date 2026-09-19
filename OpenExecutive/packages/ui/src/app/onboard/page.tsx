"use client";

import { useRouter } from "next/navigation";
import OnboardWizard from "@/components/OnboardWizard";

// Onboarding is a focused full-screen flow — exempt from the AppShell
// chrome so the wizard owns the whole viewport.
export default function OnboardPage() {
  const router = useRouter();

  function handleComplete() {
    router.push("/");
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      <main className="flex-1 overflow-y-auto">
        <OnboardWizard onComplete={handleComplete} />
      </main>
    </div>
  );
}
