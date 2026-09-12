// Ingest. Calls the external compute service for frames, audio and scenes, stores
// every frame in Convex storage, and writes four tables through internal mutations.
//
// Compare, in pixeltable/app.py:
//   Videos.insert([{'video': 'lecture.mp4', 'title': 'CS101'}])

import { action } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";

const COMPUTE_SERVICE_URL = process.env.COMPUTE_SERVICE_URL || "http://localhost:9000";

const FRAME_FPS = 1.0;
const CHUNK_SECONDS = 10.0;

const post = async (path: string, body: unknown) => {
  const resp = await fetch(`${COMPUTE_SERVICE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status}`);
  return await resp.json();
};

const decodeBase64 = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

export const ingestVideo = action({
  args: { videoUrl: v.string(), title: v.string() },
  handler: async (ctx, args) => {
    const videoId = await ctx.runMutation(internal.videos.insertVideo, {
      title: args.title,
      videoUrl: args.videoUrl,
    });

    try {
      // Frames. Each one is base64 out of the compute service, a Blob into Convex
      // storage, then one mutation hop to write the row.
      const frames = await post("/extract-frames", { video_url: args.videoUrl, fps: FRAME_FPS });
      for (let i = 0; i < frames.frames.length; i++) {
        const blob = new Blob([decodeBase64(frames.frames[i])], { type: "image/jpeg" });
        const imageStorageId = await ctx.storage.store(blob);
        await ctx.runMutation(internal.videos.insertFrame, { videoId, frameIdx: i, imageStorageId });
      }

      const audio = await post("/extract-audio", { video_url: args.videoUrl, format: "mp3" });
      await ctx.runMutation(internal.videos.setDuration, { videoId, durationSec: audio.duration_sec });
      for (let start = 0; start < audio.duration_sec; start += CHUNK_SECONDS) {
        const end = Math.min(start + CHUNK_SECONDS, audio.duration_sec);
        await ctx.runMutation(internal.videos.insertAudioChunk, { videoId, startSec: start, endSec: end });
      }

      const scenes = await post("/detect-scenes", { video_url: args.videoUrl });
      for (const scene of scenes.scenes) {
        await ctx.runMutation(internal.videos.insertScene, {
          videoId,
          startSec: scene.start_sec,
          endSec: scene.end_sec,
        });
      }

      // Two scheduled actions do the embedding. They run after this returns, and
      // nothing here learns whether they succeeded.
      await ctx.scheduler.runAfter(0, internal.processFrames.embedAllFrames, { videoId });
      await ctx.scheduler.runAfter(0, internal.processAudio.transcribeAndEmbed, { videoId });
    } catch (err) {
      await ctx.runMutation(internal.videos.updateStatus, { videoId, status: "error" });
      throw err;
    }

    // Deliberately not 'ready'. listVideos derives the true status by counting
    // rows that still have no embedding.
    return { rows: [{ id: videoId, video_title: args.title, status: "processing" }] };
  },
});
