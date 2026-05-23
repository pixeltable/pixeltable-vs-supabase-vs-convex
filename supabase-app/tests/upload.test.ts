import { describe, it, expect, beforeAll } from "vitest";
import "dotenv/config";

const SUPABASE_URL = process.env.SUPABASE_URL!;
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY!;

const FUNCTIONS_URL = `${SUPABASE_URL}/functions/v1`;

describe("POST /upload", () => {
  beforeAll(() => {
    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
      throw new Error("Missing SUPABASE_URL or SUPABASE_ANON_KEY env vars");
    }
  });

  it("should upload a text document and return id, source, modality", async () => {
    const response = await fetch(`${FUNCTIONS_URL}/upload`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        content: "Test document about machine learning fundamentals.",
        source: "test-upload.txt",
        metadata: { category: "test" },
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data).toHaveProperty("id");
    expect(data.source).toBe("test-upload.txt");
    expect(data.modality).toBe("text");
  });

  it("should upload an image via URL and return modality 'image'", async () => {
    const response = await fetch(`${FUNCTIONS_URL}/upload`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        image_url: "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/300px-PNG_transparency_demonstration_1.png",
        source: "test-image.png",
        metadata: { category: "test" },
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data).toHaveProperty("id");
    expect(data.source).toBe("test-image.png");
    expect(data.modality).toBe("image");
  });

  it("should return 500 when content and image_url are both missing", async () => {
    const response = await fetch(`${FUNCTIONS_URL}/upload`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({
        source: "empty.txt",
      }),
    });

    expect(response.status).toBe(500);
    const data = await response.json();
    expect(data).toHaveProperty("error");
  });
});
