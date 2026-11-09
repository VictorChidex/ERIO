import type { Metadata } from "next";

import { ApiUnavailable, getOpenApi, getToolDefinitions, MCP_PUBLIC_URL } from "@/lib/api";
import { countWord, toolList } from "@/lib/tools";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "API reference",
  description: "The ERIO REST API: search and filter jobs in every country with one endpoint.",
};

type Schema = { type?: string; anyOf?: Schema[]; items?: Schema; enum?: string[]; format?: string; $ref?: string };
type Parameter = { name: string; in: string; description?: string; schema?: Schema };
type Operation = { summary?: string; parameters?: Parameter[] };
type Spec = {
  paths: Record<string, Record<string, Operation>>;
  components?: { schemas?: Record<string, { properties?: Record<string, Schema & { description?: string }> }> };
};

function typeName(schema: Schema | undefined): string {
  if (!schema) return "any";
  if (schema.$ref) return schema.$ref.split("/").pop() ?? "object";
  if (schema.anyOf) return schema.anyOf.map(typeName).filter((t) => t !== "null").join(" | ") || "null";
  if (schema.enum) return "enum";
  if (schema.type === "array") return `${typeName(schema.items)}[]`;
  if (schema.format === "date-time") return "ISO 8601";
  return schema.type ?? "any";
}

async function load(): Promise<Spec | null> {
  try {
    return (await getOpenApi()) as unknown as Spec;
  } catch (error) {
    if (error instanceof ApiUnavailable) return null;
    throw error;
  }
}

const PUBLIC = (path: string) => path.startsWith("/v1/") && !path.startsWith("/v1/health") && !path.includes("openapi") && !path.includes("docs");

function ToolBlock({ title, tools }: { title: string; tools: unknown }) {
  return (
    <details className="tool-defs">
      <summary>{title}</summary>
      <pre className="code">{JSON.stringify(tools, null, 2)}</pre>
    </details>
  );
}

export default async function ApiPage() {
  const [spec, openai, gemini] = await Promise.all([
    load(),
    getToolDefinitions("openai"),
    getToolDefinitions("gemini"),
  ]);
  const tools = toolList(openai);
  const endpoints = spec
    ? Object.entries(spec.paths)
        .filter(([path]) => PUBLIC(path))
        .flatMap(([path, methods]) => Object.entries(methods).map(([method, op]) => ({ path, method, op })))
    : [];
  const jobsParams = spec?.paths["/v1/jobs"]?.get?.parameters?.filter((p) => p.in === "query") ?? [];
  const record = spec?.components?.schemas?.JobRecord?.properties ?? {};

  return (
    <>
      <div className="page-header">
        <div className="wrap">
          <div className="sect-eye">⌥ REST API</div>
          <h1 className="page-title">
            One endpoint.
            <br />
            Every country.
          </h1>
          <p className="page-sub">
            A single paginated endpoint returns normalized <code>JobRecord</code> objects with
            country, remote scope, salary and source. Bearer-token auth, OpenAPI 3.1 spec included.
          </p>
          <div className="cta-actions api-actions">
            <a className="btn-acc" href="#access">
              Get API Key
            </a>
            <a className="btn-ghost" href="/openapi.json" download="erio-openapi.json">
              Download OpenAPI Spec
            </a>
          </div>
        </div>
      </div>
      <div className="wrap">
        <div className="api-layout">
          <div className="api-left">
            <h2 className="api-section-title">Endpoints</h2>
            <div className="eps">
              {endpoints.length ? (
                endpoints.map(({ path, method, op }) => (
                  <div className="ep" key={`${method} ${path}`}>
                    <span className={`epm ${method}`}>{method.toUpperCase()}</span>
                    <span className="eph">{path}</span>
                    <span className="epd">{op.summary}</span>
                  </div>
                ))
              ) : (
                <p className="api-prose">The API spec is unavailable right now.</p>
              )}
            </div>

            <h2 className="api-section-title" id="access">
              Authentication and access
            </h2>
            <p className="api-prose">
              Send a Bearer token in the <code>Authorization</code> header. Tokens are 32 random
              bytes, shown once when created; ERIO stores only a hash. During the beta, tokens are
              issued by the ERIO team. Rate limits: <strong>100 requests a minute</strong> on the
              free tier, <strong>2,000</strong> on Pro, and 30 a minute without a token.
            </p>
            <div className="code-wrap api-code">
              <div className="ctop">
                <div className="dots">
                  <span className="dot-r" />
                  <span className="dot-y" />
                  <span className="dot-g" />
                </div>
                <span className="ctitle">Request header</span>
              </div>
              <pre className="code">
                <span className="ck">Authorization</span>
                <span className="cm">:</span> <span className="cv">Bearer YOUR_ERIO_TOKEN</span>
              </pre>
            </div>

            <h2 className="api-section-title">Query parameters — GET /v1/jobs</h2>
            <div className="param-table">
              <div className="param-row param-head">
                <span>Parameter</span>
                <span>Type</span>
                <span>Description</span>
              </div>
              {jobsParams.map((p) => (
                <div className="param-row" key={p.name}>
                  <code>{p.name}</code>
                  <span>{typeName(p.schema)}</span>
                  <span>{p.description ?? ""}</span>
                </div>
              ))}
            </div>

            <h2 className="api-section-title" id="ai">
              Use ERIO from AI assistants
            </h2>
            <p className="api-prose">
              ERIO runs a read-only MCP server
              {tools.length > 0 ? ` with ${countWord(tools.length)} tools` : ""}
              {tools.length > 0 ? ": " : ". "}
              {tools.map((tool, index) => (
                <span key={tool.name}>
                  <code>{tool.name}</code>
                  {index < tools.length - 2 ? ", " : index === tools.length - 2 ? " and " : ". "}
                </span>
              ))}
              It calls this API, so the same tokens and rate limits apply. Add it to Claude Code
              with:
            </p>
            <div className="code-wrap api-code">
              <div className="ctop">
                <span className="ctitle">Claude Code</span>
              </div>
              <pre className="code">{`claude mcp add --transport http erio ${MCP_PUBLIC_URL}`}</pre>
            </div>
            <p className="api-prose">
              Other assistants that support MCP over HTTP take the same address. For OpenAI
              function calling or Gemini function declarations, paste these definitions and send
              each call to the matching <code>/v1</code> endpoint.
            </p>
            {openai && gemini ? (
              <>
                <ToolBlock title="OpenAI function calling (tools)" tools={openai} />
                <ToolBlock title="Gemini function declarations" tools={gemini} />
              </>
            ) : (
              <p className="api-prose">The tool definitions are unavailable right now.</p>
            )}

            <h2 className="api-section-title">JobRecord</h2>
            <div className="schema-block">
              {Object.entries(record).map(([name, schema]) => (
                <div className="schema-field" key={name}>
                  <code>{name}</code> <span className="st">{typeName(schema)}</span>
                  {schema.description ? ` — ${schema.description}` : ""}
                </div>
              ))}
            </div>
          </div>

          <aside className="api-right" aria-label="Examples">
            <div className="code-wrap">
              <div className="ctop">
                <div className="dots">
                  <span className="dot-r" />
                  <span className="dot-y" />
                  <span className="dot-g" />
                </div>
                <span className="ctitle">Remote engineering jobs open to Nigeria</span>
              </div>
              <pre className="code">
                {"curl -H \"Authorization: Bearer YOUR_ERIO_TOKEN\" \\\n  \"https://api.<domain>/v1/jobs?country=NG\\\n  &remote_status=remote&role=engineering\""}
              </pre>
            </div>
            <div className="api-cards">
              <div className="code-wrap">
                <div className="ctop">
                  <span className="ctitle">Every response</span>
                </div>
                <pre className="code">
                  {"X-RateLimit-Limit: 100\nX-RateLimit-Remaining: 99\nX-RateLimit-Reset: 1793856000\nX-Request-ID: 9f2c…"}
                </pre>
              </div>
              <div className="code-wrap">
                <div className="ctop">
                  <span className="ctitle">Errors (one shape)</span>
                </div>
                <pre className="code">
                  {"{\n  \"error\": {\n    \"code\": \"rate_limited\",\n    \"message\": \"limit of 100 requests per minute reached\",\n    \"request_id\": \"9f2c…\"\n  }\n}"}
                </pre>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </>
  );
}
