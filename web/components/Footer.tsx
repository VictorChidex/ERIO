import Link from "next/link";

const REPO = "https://github.com/VictorChidex/ERIO";

export function Footer() {
  return (
    <footer id="footer">
      <div className="wrap">
        <div className="foot-in">
          <div className="foot-brand">
            <span className="fl">ERIO</span>
            <p>
              Every open job, in every country.
              <br />
              One search, one API.
            </p>
            <span className="fcopy">© 2026 ERIO</span>
          </div>
          <div className="foot-col">
            <div className="foot-col-title">Product</div>
            <Link href="/search">Search</Link>
            <Link href="/coverage">Coverage</Link>
            <Link href="/countries/ng">Jobs by country</Link>
          </div>
          <div className="foot-col">
            <div className="foot-col-title">Developers</div>
            <Link href="/api">API reference</Link>
            <a href="/openapi.json">OpenAPI spec</a>
            <Link href="/coverage">Status</Link>
          </div>
          <div className="foot-col">
            <div className="foot-col-title">Project</div>
            <a href={REPO} rel="noopener noreferrer">
              GitHub
            </a>
            <a href={`${REPO}/blob/main/docs/sources.md`} rel="noopener noreferrer">
              Data sources
            </a>
            <a href="https://www.exchangerate-api.com" rel="noopener noreferrer">
              Rates by Exchange Rate API
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
