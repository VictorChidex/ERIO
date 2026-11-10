import type { Metadata } from "next";

import { WorkspaceShell } from "@/components/workspace/WorkspaceShell";

export const metadata: Metadata = {
  title: "Your workspace",
  description:
    "Save jobs, track applications, follow searches by feed or webhook and compare your CV to a job. No account, no email, nothing sent anywhere.",
  robots: { index: false },
};

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
