import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.0";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req: Request) => {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { content, image_url, source, metadata } = await req.json();

    const openaiKey = Deno.env.get("OPENAI_API_KEY")!;
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

    const supabase = createClient(supabaseUrl, supabaseServiceKey);

    let textToEmbed: string;
    let modality: "text" | "image";

    if (image_url) {
      // Step 1: Call OpenAI Vision to generate a description of the image
      const visionResponse = await fetch("https://api.openai.com/v1/chat/completions", {
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
                { type: "image_url", image_url: { url: image_url } },
              ],
            },
          ],
          max_tokens: 300,
        }),
      });
      const visionData = await visionResponse.json();
      textToEmbed = visionData.choices[0].message.content;
      modality = "image";
    } else {
      // Text document: embed the content directly
      textToEmbed = content;
      modality = "text";
    }

    // Step 2: Call OpenAI Embeddings API to generate the vector
    const embeddingResponse = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${openaiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "text-embedding-3-small",
        input: textToEmbed,
      }),
    });
    const embeddingData = await embeddingResponse.json();
    const embedding = embeddingData.data[0].embedding;

    // Step 3: Insert document with embedding into Supabase
    const { data, error } = await supabase
      .from("documents")
      .insert({
        content: textToEmbed,
        source: source || "unknown",
        modality,
        image_url: image_url || null,
        metadata: metadata || {},
        embedding,
      })
      .select("id, source, modality")
      .single();

    if (error) throw error;

    return new Response(JSON.stringify(data), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
