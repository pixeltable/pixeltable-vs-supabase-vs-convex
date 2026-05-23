import { describe, it, expect, beforeAll } from "vitest";
import "dotenv/config";

const SUPABASE_URL = process.env.SUPABASE_URL!;
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY!;

const FUNCTIONS_URL = `${SUPABASE_URL}/functions/v1`;

describe("POST /agent/query", () => {
  beforeAll(() => {
    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
      throw new Error("Missing SUPABASE_URL or SUPABASE_ANON_KEY env vars");
    }
  });

  it("should return an answer with sources for a knowledge base question", async () => {
    const response = await fetch(`${FUNCTIONS_URL}/agent`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        message: "What is Pixeltable and what does it do?",
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data).toHaveProperty("answer");
    expect(data).toHaveProperty("sources");
    expect(data).toHaveProperty("conversation_id");
    expect(typeof data.answer).toBe("string");
    expect(Array.isArray(data.sources)).toBe(true);
  });

  it("should accept and return a conversation_id for multi-turn context", async () => {
    const conversationId = "test-convo-123";

    const response = await fetch(`${FUNCTIONS_URL}/agent`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        message: "Tell me about vector embeddings.",
        conversation_id: conversationId,
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.conversation_id).toBe(conversationId);
    expect(data.sources.length).toBeGreaterThan(0);
  });

  it("should include source metadata in the response", async () => {
    const response = await fetch(`${FUNCTIONS_URL}/agent`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        message: "How does Supabase compare to Firebase?",
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    if (data.sources.length > 0) {
      expect(data.sources[0]).toHaveProperty("source");
      expect(data.sources[0]).toHaveProperty("modality");
      expect(data.sources[0]).toHaveProperty("similarity");
    }
  });
});
