import { describe, it, expect, beforeAll } from "vitest";
import "dotenv/config";

const SUPABASE_URL = process.env.SUPABASE_URL!;
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY!;

const FUNCTIONS_URL = `${SUPABASE_URL}/functions/v1`;

describe("POST /search", () => {
  beforeAll(() => {
    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
      throw new Error("Missing SUPABASE_URL or SUPABASE_ANON_KEY env vars");
    }
  });

  it("should return search results for a text query", async () => {
    const response = await fetch(`${FUNCTIONS_URL}/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        query: "machine learning",
        limit: 3,
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data).toHaveProperty("results");
    expect(data).toHaveProperty("query", "machine learning");
    expect(Array.isArray(data.results)).toBe(true);
  });

  it("should respect the limit parameter", async () => {
    const response = await fetch(`${FUNCTIONS_URL}/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        query: "data infrastructure",
        limit: 2,
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.results.length).toBeLessThanOrEqual(2);
  });

  it("should return results with similarity scores", async () => {
    const response = await fetch(`${FUNCTIONS_URL}/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        query: "vector embeddings",
        limit: 5,
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    if (data.results.length > 0) {
      expect(data.results[0]).toHaveProperty("similarity");
      expect(data.results[0]).toHaveProperty("content");
      expect(data.results[0]).toHaveProperty("source");
    }
  });
});
