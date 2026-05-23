import { describe, it, expect } from 'vitest';

const CONVEX_HTTP_URL = process.env.CONVEX_URL?.replace('.convex.cloud', '.convex.site') ?? '';

describe('POST /upload', () => {
  it('uploads a text document and returns id + metadata', async () => {
    const response = await fetch(`${CONVEX_HTTP_URL}/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: 'Convex is a reactive backend platform with built-in vector search.',
        source: 'test-upload',
        metadata: { tag: 'platform' },
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.id).toBeDefined();
    expect(data.source).toBe('test-upload');
    expect(data.modality).toBe('text');
  });

  it('uploads an image document via URL', async () => {
    const response = await fetch(`${CONVEX_HTTP_URL}/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        imageUrl: 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png',
        source: 'test-image',
        metadata: { format: 'png' },
      }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(data.id).toBeDefined();
    expect(data.modality).toBe('image');
  });

  it('returns error when neither content nor imageUrl provided', async () => {
    const response = await fetch(`${CONVEX_HTTP_URL}/upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: 'bad-request' }),
    });

    expect(response.status).not.toBe(200);
  });
});
