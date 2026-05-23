import { describe, it, expect } from 'vitest';

const CONVEX_HTTP_URL = process.env.CONVEX_URL?.replace('.convex.cloud', '.convex.site') ?? '';

describe('POST /agent/query', () => {
  it('returns an answer with sources and conversationId', async () => {
    // Seed a document for the agent to retrieve
    await fetch(`${CONVEX_HTTP_URL}/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: 'Convex actions run in a Node.js environment and can call external APIs.',
        source: 'test-agent-doc',
      }),
    });

    await new Promise((resolve) => setTimeout(resolve, 2000));

    const response = await fetch(`${CONVEX_HTTP_URL}/agent/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: 'What runtime do Convex actions use?',
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.answer).toBeDefined();
    expect(typeof data.answer).toBe('string');
    expect(data.sources).toBeDefined();
    expect(Array.isArray(data.sources)).toBe(true);
    expect(data.conversationId).toBeDefined();
  });

  it('accepts an existing conversationId', async () => {
    const response = await fetch(`${CONVEX_HTTP_URL}/agent/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: 'Tell me more about that.',
        conversationId: 'test-conv-123',
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.conversationId).toBe('test-conv-123');
  });
});
