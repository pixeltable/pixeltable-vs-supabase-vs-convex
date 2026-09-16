// Ingest. Calls the external compute service, stores every frame in Convex storage,
// and writes four tables through batched internal mutations.
//
// Compare, in pixeltable/app.py:
//   Videos.insert([{'video': 'lecture.mp4', 'title': 'CS101'}])

import { action } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";
import type { Id } from "./_generated/dataModel";
import { compute } from "./compute";

const FRAME_FPS = 1.0;
const CHUNK_SECONDS = 10.0;

const decodeBase64 = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

export const ingestVideo = action({
  args: { videoUrl: v.string(), title: v.string() },
  // Convex needs the explicit return type: an action that calls ctx.runMutation on
  // functions in its own dependency graph is a circular reference TypeScript cannot
  // infer through.
  handler: async (ctx, args): Promise<{ rows: { id: string; video_title: string; status: string }[] }> => {
    const videoId: Id<"videos"> = await ctx.runMutation(internal.videos.insertVideo, {
      title: args.title,
      videoUrl: args.videoUrl,
    });

    try {
      // Frames: extract, embed the whole batch in one call, store each blob, one write.
      const { frames } = await compute("/extract-frames", { video_url: args.videoUrl, fps: FRAME_FPS });
      const { embeddings } = await compute("/embed-clip", { images_b64: frames });
      const frameRows = await Promise.all(frames.map(async (b64: string, i: number) => ({
        frameIdx: i,
        imageStorageId: await ctx.storage.store(new Blob([decodeBase64(b64)], { type: "image/jpeg" })),
        embedding: embeddings[i],
      })));
      await ctx.runMutation(internal.videos.insertFrames, { videoId, rows: frameRows });

      // Audio: one extraction, one transcription per chunk span, one embedding call.
      const audio = await compute("/extract-audio", { video_url: args.videoUrl, format: "mp3" });
      const spans = [];
      for (let start = 0; start < audio.duration_sec; start += CHUNK_SECONDS) {
        spans.push({ startSec: start, endSec: Math.min(start + CHUNK_SECONDS, audio.duration_sec) });
      }
      const transcripts = await Promise.all(
        spans.map((s) =>
          compute("/transcribe", { audio_b64: audio.audio_b64, start_sec: s.startSec, end_sec: s.endSec })
            .then((t) => t.text)
        ),
      );
      const { embeddings: textEmbeddings } = await compute("/embed-text", { texts: transcripts });
      await ctx.runMutation(internal.videos.insertChunks, {
        videoId,
        rows: spans.map((s, i) => ({ ...s, transcript: transcripts[i], embedding: textEmbeddings[i] })),
      });

      const { scenes } = await compute("/detect-scenes", { video_url: args.videoUrl });
      await ctx.runMutation(internal.videos.insertScenes, {
        videoId,
        rows: scenes.map((s: { start_sec: number; end_sec: number }) => ({
          startSec: s.start_sec,
          endSec: s.end_sec,
        })),
      });

      await ctx.runMutation(internal.videos.finishVideo, {
        videoId,
        durationSec: audio.duration_sec,
        sceneCount: scenes.length,
        status: "ready",
      });
    } catch (err) {
      await ctx.runMutation(internal.videos.markError, { videoId });
      throw err;
    }

    return { rows: [{ id: String(videoId), video_title: args.title, status: "ready" }] };
  },
});
