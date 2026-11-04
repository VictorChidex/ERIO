import { getApiHealth } from "@/lib/api";

// Rendered per request so the status always reflects the live API.
export const dynamic = "force-dynamic";

export default async function HomePage() {
  const health = await getApiHealth();

  return (
    <section className="hero">
      <h1>Every open job, in every country.</h1>
      <p>
        ERIO indexes job postings straight from applicant tracking systems, cleans them into one
        record and keeps them fresh.
      </p>
      <span className="status" data-ok={health !== null} role="status">
        <span className="status-dot" aria-hidden="true" />
        {health ? (
          <>
            API online <span className="mono">v{health.version}</span>
          </>
        ) : (
          "API unreachable"
        )}
      </span>
    </section>
  );
}
