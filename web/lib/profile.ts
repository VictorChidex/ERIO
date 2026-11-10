import { call, getToken, type SkillTag, WorkspaceError } from "@/lib/workspace";

export type Accent = "default" | "teal" | "violet" | "amber" | "rose";
export type Density = "comfortable" | "compact";
export type StartTab = "overview" | "tracker" | "searches" | "cv";
export type Card = "stats" | "next" | "matches" | "searches";

export type Prefs = { accent: Accent; density: Density; start_tab: StartTab; hidden_cards: Card[] };
export type MailState = {
  email: string;
  frequency: "daily" | "weekly";
  confirmed: boolean;
  paused: boolean;
  last_sent_at: string | null;
};
export type Profile = {
  skills: SkillTag[];
  titles: string[];
  countries: string[];
  remote_only: boolean;
  min_score: number;
  prefs: Prefs;
  mail: MailState | null;
};
export type Pick = {
  job_id: string;
  title: string;
  company: string;
  location: string | null;
  apply_url: string;
  score: number;
  why: string;
};
export type AlertState = { email: string; frequency: "daily" | "weekly"; paused: boolean; confirmed: boolean };

export const ACCENTS: Record<Accent, { label: string; color: string | null }> = {
  default: { label: "ERIO blue", color: null },
  teal: { label: "Teal", color: "#0d9488" },
  violet: { label: "Violet", color: "#7c5cff" },
  amber: { label: "Amber", color: "#d97706" },
  rose: { label: "Rose", color: "#e11d48" },
};

export const CARDS: { id: Card; label: string }[] = [
  { id: "stats", label: "Where things stand" },
  { id: "next", label: "Needs your attention" },
  { id: "matches", label: "New since you last looked" },
  { id: "searches", label: "Compare your CV" },
];

export const START_TABS: { id: StartTab; label: string; href: string }[] = [
  { id: "overview", label: "Overview", href: "/workspace" },
  { id: "tracker", label: "Tracker", href: "/workspace/tracker" },
  { id: "searches", label: "Saved searches", href: "/workspace/searches" },
  { id: "cv", label: "Profile and alerts", href: "/workspace/alerts" },
];

export const COUNTRY_CHOICES: [string, string][] = [
  ["NG", "Nigeria"],
  ["GH", "Ghana"],
  ["KE", "Kenya"],
  ["ZA", "South Africa"],
  ["GB", "United Kingdom"],
  ["US", "United States"],
  ["CA", "Canada"],
  ["DE", "Germany"],
  ["NL", "Netherlands"],
  ["IN", "India"],
  ["AE", "United Arab Emirates"],
  ["AU", "Australia"],
];

/** Sends a CV file to be read for skills; the file is not stored anywhere. */
export async function uploadResume(file: File): Promise<SkillTag[]> {
  const token = getToken();
  if (file.size > 2 * 1024 * 1024) throw new WorkspaceError("That file is over 2 MB.", 413);
  let response: Response;
  try {
    response = await fetch("/workspace/api/profile/resume", {
      method: "POST",
      headers: { "X-Workspace-Token": token ?? "", "X-Filename": file.name },
      body: file,
      cache: "no-store",
    });
  } catch {
    throw new WorkspaceError("Could not reach ERIO. Check your connection.", 0);
  }
  const data = (await response.json().catch(() => ({}))) as { skills?: SkillTag[]; error?: { message?: string } | string };
  if (!response.ok) {
    const message = typeof data.error === "string" ? data.error : (data.error?.message ?? `Something went wrong (${response.status}).`);
    throw new WorkspaceError(message, response.status);
  }
  return data.skills ?? [];
}

export const saveProfile = (patch: Partial<Omit<Profile, "skills" | "mail" | "prefs">> & { skills?: string[]; prefs?: Prefs }) =>
  call<Profile>("PUT", "profile", patch);

export const findJobs = () => call<Pick[]>("GET", "profile/jobs");
export const askForAlerts = (email: string, frequency: "daily" | "weekly") =>
  call<MailState>("PUT", "mail", { email, frequency });
export const stopAlerts = () => call<void>("DELETE", "mail");

// The links in the emails: no workspace token, the secret is in the link.
export const alertState = (token: string) => call<AlertState>("GET", `alerts/${token}`, undefined, null);
export const confirmAlerts = (token: string) => call<AlertState>("POST", "alerts/confirm", { token }, null);
export const changeAlerts = (token: string, patch: { paused?: boolean; frequency?: "daily" | "weekly" }) =>
  call<AlertState>("PATCH", `alerts/${token}`, patch, null);
export const deleteAlerts = (token: string) => call<void>("DELETE", `alerts/${token}`, undefined, null);
