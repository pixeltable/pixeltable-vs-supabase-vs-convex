// GET /videos. Counts have to be gathered per video, and the stored `status`
// column cannot be trusted, so the real one is derived in SQL.
//
// Compare, in pixeltable/app.py:
//   Videos.select(video_title=Videos.title, duration_sec=Videos.duration_sec,
//                 scene_count=pxtf.json.len(Videos.scenes))

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

Deno.serve(async () => {
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

  const { data: videos, error } = await supabase
    .from("videos")
    .select("id, title")
    .order("title");

  if (error) {
    return new Response(JSON.stringify({ error: error.message }), { status: 500 });
  }

  // One round trip per video per count. Pixeltable reads this off the base table.
  const rows = [];
  for (const video of videos || []) {
    const { count: sceneCount } = await supabase
      .from("scenes")
      .select("id", { count: "exact", head: true })
      .eq("video_id", video.id);
    const { data: span } = await supabase
      .from("audio_chunks")
      .select("end_sec")
      .eq("video_id", video.id)
      .order("end_sec", { ascending: false })
      .limit(1);
    const { data: status } = await supabase.rpc("video_status", { v_id: video.id });

    rows.push({
      video_title: video.title,
      duration_sec: span?.[0]?.end_sec ?? 0,
      scene_count: sceneCount ?? 0,
      status,
    });
  }

  return new Response(JSON.stringify({ rows }), {
    headers: { "Content-Type": "application/json" },
  });
});
