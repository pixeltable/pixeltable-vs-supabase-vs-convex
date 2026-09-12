/**
 * Seed the Supabase video pipeline with fixture videos.
 * Calls the ingest Edge Function for each video.
 *
 * Usage: npx tsx scripts/seed.ts
 */

import { createClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.SUPABASE_URL!;
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY!;
const INGEST_FUNCTION_URL = `${SUPABASE_URL}/functions/v1/ingest`;

const FIXTURES = [
  "lecture_data_structures.mp4",
  "whiteboard_algorithms.mp4",
  "code_review_session.mp4",
].map((name) => ({ video: `/fixtures/videos/${name}`, title: name }));

async function seed() {
  console.log("Seeding videos...");

  for (const fixture of FIXTURES) {
    console.log(`  Ingesting: ${fixture.title}`);
    const resp = await fetch(INGEST_FUNCTION_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${SUPABASE_SERVICE_KEY}`,
      },
      body: JSON.stringify(fixture),
    });

    if (!resp.ok) {
      console.error(`  ERROR: ${await resp.text()}`);
    } else {
      const data = await resp.json();
      console.log(`  OK: ${JSON.stringify(data.rows?.[0] ?? data)}`);
    }
  }

  console.log("Done.");
}

seed().catch(console.error);
