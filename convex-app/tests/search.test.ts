import { describe, it, expect } from 'vitest';

const CONVEX_HTTP_URL = process.env.CONVEX_URL?.replace('.convex.cloud', '.convex.site') ?? '';

describe('POST /search', () => {
  it('returns results for a semantic query', async () => {
    // First, upload a document to search against
    await fetch(`${CONVEX_HTTP_URL}/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: 'Vector databases store embeddings for similarity search over unstructured data.',
        source: 'test-search-doc',
      }),
    });

    // Allow time for the action to complete
    await new Promise((resolve) => setTimeout(resolve, 2000));

    const response = await fetch(`${CONVEX_HTTP_URL}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: 'How do vector databases work?',
        limit: 5,
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.results).toBeDefined();
    expect(Array.isArray(data.results)).toBe(true);

    if (data.results.length > 0) {
      expect(data.results[0].score).toBeDefined();
      expect(data.results[0].content).toBeDefined();
    }
  });

  it('respects the limit parameter', async () => {
    const response = await fetch(`${CONVEX_HTTP_URL}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: 'test query',
        limit: 2,
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.results.length).toBeLessThanOrEqual(2);
  });
});
