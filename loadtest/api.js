// k6 load test for the public API (spec section 10): 200 requests per second,
// p95 under 300 ms, under 0.1% errors. How to run it and the results: docs/load-test.md.
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE_URL || "http://api:8000";
// The target is 200 requests a second for 2 minutes; RATE and DURATION let a
// smaller machine find the rate it can sustain.
const RATE = Number(__ENV.RATE || 200);
const DURATION = __ENV.DURATION || "2m";
const COUNTRIES = ["US", "GB", "NG", "KE", "IN", "BR", "DE", "MX", "ZA", "SG", "CA", "IE", "PH", "EG", "GH"];
const ROLES = ["engineering", "sales", "operations", "data", "product", "design", "marketing"];
const WORDS = ["engineer", "manager", "sales", "data", "support", "designer", "analyst", "product"];

export const options = {
  scenarios: {
    warmup: {
      executor: "constant-arrival-rate", rate: Math.min(50, RATE), timeUnit: "1s", duration: "30s",
      preAllocatedVUs: 50, maxVUs: 200, exec: "traffic", tags: { phase: "warmup" },
    },
    steady: {
      executor: "constant-arrival-rate", rate: RATE, timeUnit: "1s", duration: DURATION,
      startTime: "30s", preAllocatedVUs: 200, maxVUs: 600, exec: "traffic",
      tags: { phase: "steady" },
    },
  },
  thresholds: {
    "http_req_duration{phase:steady}": ["p(95)<300"],
    "http_req_failed{phase:steady}": ["rate<0.001"],
  },
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
};

const pick = (list) => list[Math.floor(Math.random() * list.length)];

export function setup() {
  // Real job IDs for the detail requests.
  const ids = [];
  for (const country of COUNTRIES.slice(0, 6)) {
    const page = http.get(`${BASE}/v1/jobs?country=${country}&per_page=25`).json("data") || [];
    page.forEach((job) => ids.push(job.canonical_id));
  }
  return { ids };
}

export function traffic(data) {
  const roll = Math.random();
  let url;
  if (roll < 0.45) {
    url = `/v1/jobs?country=${pick(COUNTRIES)}`;
    if (Math.random() < 0.3) url += "&remote_status=remote";
    if (Math.random() < 0.3) url += `&role=${pick(ROLES)}`;
    if (Math.random() < 0.15) url += "&salary_min_usd=50000&sort=salary";
  } else if (roll < 0.6) {
    url = `/v1/jobs?q=${pick(WORDS)}&per_page=25`;
  } else if (roll < 0.8) {
    url = `/v1/jobs/${pick(data.ids)}`;
  } else if (roll < 0.9) {
    url = "/v1/countries";
  } else if (roll < 0.95) {
    url = "/v1/platforms";
  } else {
    url = "/v1/stats";
  }
  const response = http.get(`${BASE}${url}`, { tags: { name: url.split("?")[0].replace(/j_[0-9a-f]+/, "{id}") } });
  check(response, { "status 200": (r) => r.status === 200 });
}
