import { createClient } from "@supabase/supabase-js";
import * as fs from "fs";
import * as path from "path";
import "dotenv/config";

const supabaseUrl = process.env.SUPABASE_URL!;
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY!;
const openaiKey = process.env.OPENAI_API_KEY!;

const supabase = createClient(supabaseUrl, supabaseServiceKey);

const FIXTURES_DIR = path.resolve(__dirname, "../../fixtures");

async function getEmbedding(text: string): Promise<number[]> {
  const response = await fetch("https://api.openai.com/v1/embeddings", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${openaiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "text-embedding-3-small",
      input: text,
    }),
  });
  const data = await response.json();
  return data.data[0].embedding;
}

async function describeImage(imageUrl: string): Promise<string> {
  const response = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${openaiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "gpt-4o-mini",
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: "Describe this image in detail for search indexing." },
            { type: "image_url", image_url: { url: imageUrl } },
          ],
        },
      ],
      max_tokens: 300,
    }),
  });
  const data = await response.json();
  return data.choices[0].message.content;
}

interface Fixture {
  content?: string;
  image_url?: string;
  source: string;
  metadata?: Record<string, unknown>;
}

async function seed() {
  console.log("Loading fixtures from:", FIXTURES_DIR);

  const fixtureFiles = fs.readdirSync(FIXTURES_DIR).filter((f) => f.endsWith(".json"));

  if (fixtureFiles.length === 0) {
    console.log("No fixture files found. Creating sample fixtures...");
    await seedSampleData();
    return;
  }

  for (const file of fixtureFiles) {
    const fixtures: Fixture[] = JSON.parse(
      fs.readFileSync(path.join(FIXTURES_DIR, file), "utf-8")
    );

    console.log(`Processing ${fixtures.length} items from ${file}...`);

    // Manual embedding loop — each document requires a separate API call
    for (const fixture of fixtures) {
      let textToEmbed: string;
      let modality: "text" | "image";

      if (fixture.image_url) {
        console.log(`  Describing image: ${fixture.source}`);
        textToEmbed = await describeImage(fixture.image_url);
        modality = "image";
      } else {
        textToEmbed = fixture.content!;
        modality = "text";
      }

      console.log(`  Embedding: ${fixture.source}`);
      const embedding = await getEmbedding(textToEmbed);

      const { error } = await supabase.from("documents").insert({
        content: textToEmbed,
        source: fixture.source,
        modality,
        image_url: fixture.image_url || null,
        metadata: fixture.metadata || {},
        embedding,
      });

      if (error) {
        console.error(`  Error inserting ${fixture.source}:`, error.message);
      } else {
        console.log(`  Inserted: ${fixture.source} (${modality})`);
      }
    }
  }

  console.log("Seeding complete.");
}

async function seedSampleData() {
  const samples: Fixture[] = [
    {
      content:
        "Pixeltable is an open-source Python library for declarative multimodal data infrastructure. It handles storage, transformation, indexing, and orchestration of data across images, video, audio, and documents.",
      source: "pixeltable-overview.txt",
      metadata: { category: "documentation" },
    },
    {
      content:
        "Supabase is an open-source Firebase alternative built on PostgreSQL. It provides authentication, storage, real-time subscriptions, and edge functions.",
      source: "supabase-overview.txt",
      metadata: { category: "documentation" },
    },
    {
      content:
        "Vector embeddings represent semantic meaning as high-dimensional numerical arrays. They enable similarity search by measuring distances between vectors in embedding space.",
      source: "embeddings-explainer.txt",
      metadata: { category: "technical" },
    },
  ];

  for (const sample of samples) {
    console.log(`  Embedding: ${sample.source}`);
    const embedding = await getEmbedding(sample.content!);

    const { error } = await supabase.from("documents").insert({
      content: sample.content,
      source: sample.source,
      modality: "text",
      metadata: sample.metadata || {},
      embedding,
    });

    if (error) {
      console.error(`  Error: ${error.message}`);
    } else {
      console.log(`  Inserted: ${sample.source}`);
    }
  }

  console.log("Sample seeding complete.");
}

seed().catch(console.error);
