# Security checklist

Controls from spec section 9, with where each is enforced. "CI" means a required check blocks the merge. Reviewed 2026-11-05 (step 13).

| Control | Status | How |
| --- | --- | --- |
| No credential in the repo | Done | Credential-word check (D-08) and gitleaks over the full history, both in CI |
| No credential in environment variables | Done | Settings hold addresses only; the AI gateway gets tokens from a credential source, never the environment (D-17); compose files pass no credential |
| No credential in images | Done | Trivy credential scan of both images in CI (one of its default scanners) |
| API tokens: 32 random bytes, hashed, revocable, one owner | Done | `erio_api.access`, `python -m erio_api.tokens` (step 9) |
| Crawler: only registered hosts | Done | `PoliteFetcher` host allow-list built from the connectors |
| Crawler: no private addresses (server-side request forgery) | Done | Every host is resolved and must be a public address before any request; HTTPS only; redirects are not followed |
| Crawler: response cap, robots.txt, crawl delay | Done | 10 MB cap; robots.txt and Crawl-delay honoured |
| Job descriptions sanitized before storage and before rendering | Done | nh3 allow-list when normalized; again in `GET /v1/jobs/{id}` on the way out; JSON-LD escapes `<` |
| Website: Content Security Policy | Done | Per-request nonce, `strict-dynamic`, no inline script without the nonce, `frame-ancestors 'none'`, `object-src 'none'` (`web/middleware.ts`); end-to-end tests pass under it |
| Website: HSTS and hardening headers | Done | HSTS (2 years, preload), `nosniff`, `X-Frame-Options: DENY`, referrer and permissions policies (`web/next.config.ts`). HSTS takes effect once served over TLS |
| TLS everywhere | Staging | CloudFront and load balancer certificates come with Terraform (D-14) |
| Least-privilege IAM per service; database only inside the VPC | Staging | Terraform (D-14); locally every port listens on 127.0.0.1 only |
| Dependency scanning | Done | `pip-audit` on the locked Python dependencies and `npm audit` on what the site ships, both in CI; Dependabot opens weekly updates for uv, npm, Actions and base images |
| Image scanning | Done | Trivy: no fixable high or critical vulnerability in either image, in CI. The website image no longer ships npm (its bundled packages carried 10 high findings); the Python image no longer carries the uv download cache |
| Internal endpoints | Done | `/metrics` answers only internal networks (D-15); the metrics exporter and Ollama publish no host port; the MCP server checks the Host header (DNS-rebinding protection) and exposes read-only tools |
| Audit log of admin actions | Not yet | Comes with the admin view (pausing sources, editing companies, revoking tokens) |
| Local monitoring tools | Local only | Grafana runs with anonymous viewers and no sign-in, bound to 127.0.0.1. Staging uses the cloud's managed Grafana or single sign-on |

## Weekly triage

- `npm audit` (all dependencies) reports 6 moderate findings in `minimatch`, used only by the linting tools (`@typescript-eslint`), not shipped. The fix needs a major upgrade; take it when typescript-eslint releases one.
