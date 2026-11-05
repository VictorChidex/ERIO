import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test } from "@playwright/test";

// lib/api reads ERIO_API_URL when it is first imported, so each test sets the
// address and then loads a fresh copy of the module.
async function loadClient(apiUrl: string) {
  process.env.ERIO_API_URL = apiUrl;
  return import(`../lib/api.ts?url=${encodeURIComponent(apiUrl)}`) as Promise<
    typeof import("../lib/api")
  >;
}

function serve(status: number, body: unknown): Promise<Server> {
  const server = createServer((_req, res) => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

test("returns the API's health when it answers", async () => {
  const server = await serve(200, { status: "ok", version: "9.9.9" });
  try {
    const { port } = server.address() as AddressInfo;
    const { getApiHealth } = await loadClient(`http://127.0.0.1:${port}`);
    expect(await getApiHealth()).toEqual({ status: "ok", version: "9.9.9" });
  } finally {
    server.close();
  }
});

test("returns null when the API answers with an error", async () => {
  const server = await serve(503, { status: "unavailable" });
  try {
    const { port } = server.address() as AddressInfo;
    const { getApiHealth } = await loadClient(`http://127.0.0.1:${port}`);
    expect(await getApiHealth()).toBeNull();
  } finally {
    server.close();
  }
});

test("returns null when the API cannot be reached", async () => {
  // Port 9 (discard) has nothing listening on a normal machine or CI runner.
  const { getApiHealth } = await loadClient("http://127.0.0.1:9");
  expect(await getApiHealth()).toBeNull();
});
