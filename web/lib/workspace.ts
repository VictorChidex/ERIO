"use client";

// Browser side of the anonymous workspace. The token (256 random bits) lives in localStorage;
// the server keeps only its hash. The "workspace link" carries it in the URL fragment, which
// browsers never send to any server. Nothing here identifies a person.

import { useCallback, useEffect, useSyncExternalStore } from "react";

const TOKEN_KEY = "erio.workspace.token";
const CV_KEY = "erio.cv.text";
const CV_SKILLS_KEY = "erio.cv.skills";
const TOKEN_SHAPE = /^erw_[A-Za-z0-9_-]{43}$/;

export type Stage = "saved" | "applied" | "interviewing" | "offer" | "rejected" | "withdrawn";
export const STAGES: Stage[] = ["saved", "applied", "interviewing", "offer", "rejected", "withdrawn"];
export const STAGE_LABELS: Record<Stage, string> = {
  saved: "Saved",
  applied: "Applied",
  interviewing: "Interviewing",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

export type TimelineEvent = { id: number; at: string; kind: string; stage: string | null; text: string | null };
export type JobState = { status: string | null; closed_at: string | null; changes: string[] };
export type Application = {
  id: number;
  job_id: string | null;
  title: string;
  company: string;
  location: string | null;
  url: string | null;
  stage: Stage;
  notes: string;
  applied_on: string | null;
  follow_up_on: string | null;
  stage_changed_at: string;
  created_at: string;
  updated_at: string;
  job: JobState | null;
  nudge: string | null;
  events: TimelineEvent[] | null;
};
export type SavedSearch = {
  id: number;
  name: string;
  params: Record<string, unknown>;
  feed_token: string;
  webhook_url: string | null;
  webhook_disabled: boolean;
  webhook_failures: number;
  created_at: string;
  new_count: number;
};
export type SearchMatch = {
  job_id: string;
  title: string;
  company: string;
  location: string | null;
  apply_url: string;
  matched_at: string;
  is_new: boolean;
};
export type Summary = {
  created_at: string;
  counts: Record<string, number>;
  limits: Record<string, number>;
};
export type SkillTag = { id: string; label: string; cat: string };
export type RankedJob = {
  job: { canonical_id: string; title: string; company: { name: string }; location_text: string | null; remote_status: string };
  score: number;
  matched: SkillTag[];
  missing: SkillTag[];
  explanation: string;
};
export type JobMatch = {
  score: number;
  matched: SkillTag[];
  missing: SkillTag[];
  required: SkillTag[];
  explanation: string;
  kit: string;
};

// --- token store ---------------------------------------------------------------------------

type Listener = () => void;
const listeners = new Set<Listener>();
let savedItems: Map<string, { id: number; stage: Stage }> | null = null;
let savedLoading = false;

function emit() {
  listeners.forEach((fn) => fn());
}

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Private browsing can refuse storage; the workspace then lasts only until the page closes.
  }
}

let memoryToken: string | null = null;

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  const stored = readStorage(TOKEN_KEY) ?? memoryToken;
  return stored && TOKEN_SHAPE.test(stored) ? stored : null;
}

export function setToken(token: string | null) {
  memoryToken = token;
  writeStorage(TOKEN_KEY, token);
  savedItems = null;
  emit();
}

/** If the address carries a workspace link (#k=<token>), keep the token and clear the address. */
export function adoptLinkFromAddress(): boolean {
  const match = /(?:^|[#&])k=([A-Za-z0-9_-]+)/.exec(window.location.hash);
  const token = match?.[1];
  if (!token || !TOKEN_SHAPE.test(token)) return false;
  setToken(token);
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  return true;
}

export function workspaceLink(token: string): string {
  return `${window.location.origin}/workspace#k=${token}`;
}

/** Accepts a whole workspace link or a bare token. */
export function tokenFromLink(text: string): string | null {
  const match = /(erw_[A-Za-z0-9_-]{43})/.exec(text);
  return match?.[1] ?? null;
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === TOKEN_KEY) {
      savedItems = null;
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** The workspace token, or null; undefined while the page has not read storage yet. */
export function useToken(): string | null | undefined {
  return useSyncExternalStore(
    subscribe,
    () => getToken(),
    () => undefined,
  );
}

// --- requests ------------------------------------------------------------------------------

export class WorkspaceError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function call<T>(method: string, path: string, body?: unknown, token = getToken()): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers["X-Workspace-Token"] = token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(path ? `/workspace/api/${path}` : "/workspace/api", {
      method,
      headers,
      body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new WorkspaceError("Could not reach ERIO. Check your connection.", 0);
  }
  if (response.status === 401 && path !== "") {
    // The workspace was deleted or the token is wrong: forget it so the page offers a new one.
    setToken(null);
  }
  if (!response.ok) {
    let message = `Something went wrong (${response.status}).`;
    try {
      const data = (await response.json()) as { error?: { message?: string } | string };
      if (typeof data.error === "string") message = data.error;
      else if (data.error?.message) message = data.error.message;
    } catch {
      // keep the generic message
    }
    throw new WorkspaceError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function createWorkspace(): Promise<string> {
  const made = await call<{ token: string }>("POST", "", undefined, null);
  setToken(made.token);
  return made.token;
}

// --- saved jobs (shared by every Save button on the page) -----------------------------------

async function loadSaved() {
  if (savedLoading || !getToken()) return;
  savedLoading = true;
  try {
    const data = await call<{ items: { job_id: string; id: number; stage: Stage }[] }>("GET", "saved-ids");
    savedItems = new Map(data.items.map((item) => [item.job_id, { id: item.id, stage: item.stage }]));
  } catch {
    savedItems = new Map();
  } finally {
    savedLoading = false;
    emit();
  }
}

export function useSaved(jobId: string): { loaded: boolean; saved: { id: number; stage: Stage } | null } {
  const token = useToken();
  const snapshot = useSyncExternalStore(
    subscribe,
    () => savedItems,
    () => null,
  );
  useEffect(() => {
    if (token && savedItems === null) void loadSaved();
  }, [token, snapshot]);
  if (!token) return { loaded: token === null, saved: null };
  return { loaded: snapshot !== null, saved: snapshot?.get(jobId) ?? null };
}

export async function saveJob(jobId: string): Promise<void> {
  if (!getToken()) await createWorkspace();
  const app = await call<Application>("POST", "applications", { job_id: jobId });
  savedItems = new Map(savedItems ?? []).set(jobId, { id: app.id, stage: app.stage });
  emit();
}

export async function unsaveJob(jobId: string, applicationId: number): Promise<void> {
  await call<void>("DELETE", `applications/${applicationId}`);
  const next = new Map(savedItems ?? []);
  next.delete(jobId);
  savedItems = next;
  emit();
}

// --- CV kept in this browser only ------------------------------------------------------------

export function getCvText(): string {
  return readStorage(CV_KEY) ?? "";
}
export function setCvText(text: string | null) {
  writeStorage(CV_KEY, text);
}
export function getCvSkills(): string[] {
  try {
    const raw = readStorage(CV_SKILLS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}
export function setCvSkills(ids: string[] | null) {
  writeStorage(CV_SKILLS_KEY, ids === null ? null : JSON.stringify(ids));
  emit();
}
export function useCvSkills(): string[] {
  const raw = useSyncExternalStore(
    subscribe,
    () => readStorage(CV_SKILLS_KEY) ?? "",
    () => "",
  );
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Run once on mount in the workspace layout: take a workspace link from the address. */
export function useAdoptLink() {
  const adopt = useCallback(() => {
    adoptLinkFromAddress();
  }, []);
  useEffect(() => {
    adopt();
    window.addEventListener("hashchange", adopt);
    return () => window.removeEventListener("hashchange", adopt);
  }, [adopt]);
}
