import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.0";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { message, conversation_id } = await req.json();

    const openaiKey = Deno.env.get("OPENAI_API_KEY")!;
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

    const supabase = createClient(supabaseUrl, supabaseServiceKey);

    // Step 1: Embed the user's message for retrieval
    const embeddingResponse = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${openaiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "text-embedding-3-small",
        input: message,
      }),
    });
    const embeddingData = await embeddingResponse.json();
    const queryEmbedding = embeddingData.data[0].embedding;

    // Step 2: Retrieve top-5 relevant documents via pgvector RPC
    const { data: context, error: searchError } = await supabase.rpc("search_documents", {
      query_embedding: queryEmbedding,
      match_count: 5,
    });

    if (searchError) throw searchError;

    // Step 3: Format retrieved documents as context for the LLM
    const contextText = context
      .map((doc: any, i: number) => `[${i + 1}] (${doc.source}): ${doc.content}`)
      .join("\n\n");

    // Step 4: Call OpenAI Chat Completions with RAG context
    const chatResponse = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${openaiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        messages: [
          {
            role: "system",
            content: `You are a helpful knowledge base assistant. Answer questions using ONLY the provided context. If the context doesn't contain relevant information, say so. Cite sources using [n] notation.

Context:
${contextText}`,
          },
          { role: "user", content: message },
        ],
        temperature: 0.3,
        max_tokens: 1000,
      }),
    });
    const chatData = await chatResponse.json();
    const answer = chatData.choices[0].message.content;

    // Step 5: Return the answer with source attribution
    const sources = context.map((doc: any) => ({
      source: doc.source,
      modality: doc.modality,
      similarity: doc.similarity,
    }));

    const resolvedConversationId = conversation_id || crypto.randomUUID();

    return new Response(
      JSON.stringify({ answer, sources, conversation_id: resolvedConversationId }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
