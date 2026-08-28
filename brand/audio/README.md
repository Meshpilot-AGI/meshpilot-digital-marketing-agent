# brand/audio — replacement audio tracks

Drop per-brand background-music tracks here for the `replace_audio` ffmpeg
transform (see `src/glitch_signal/media/ffmpeg.py`). One file per brand,
named by `<brand_id>_<slot>.mp3` (or .m4a / .wav — anything ffmpeg reads).

Audio files in this directory are **gitignored** (see `.gitignore`)
because licensing terms typically forbid redistribution via public repo.
Only `README.md` and `.gitkeep` are committed.

## Requirements

- Stereo or mono, any sample rate (ffmpeg re-encodes to AAC at 128k).
- Length ≥ a few seconds. Shorter tracks are auto-looped to cover the
  video via `-stream_loop -1`. Longer tracks get truncated via `-shortest`.
- **License must permit commercial use** on the brand's social channels.
  CC0 / CC-BY (with in-caption attribution) / royalty-free with a paid
  license. Never use a track that could trigger Content-ID on TikTok or
  we've swapped one Content-ID mute for another.

## Recommended sources

- **Pixabay Music** — https://pixabay.com/music/ — CC0, no attribution
  required, commercial use allowed. Filter by "Calm", "Ambient",
  "Meditation" for Ayurvedic / wellness brands. Download requires a
  (free) account.
- **YouTube Audio Library** — https://studio.youtube.com/ (Audio Library
  tab) — free, commercial use, some tracks require attribution.
- **Free Music Archive** — https://freemusicarchive.org/ — mix of
  licenses, filter to CC0/CC-BY.
- **Uppbeat** — https://uppbeat.io/ — free tier with attribution, paid
  tier without.

## Wiring a track into a brand

After dropping the file (e.g. `brand/audio/nmahya_bgm.mp3`), edit the
brand config to route the transform:

```json
"media_pipeline": {
  "tiktok": [
    {"name": "replace_audio", "audio_path": "brand/audio/nmahya_bgm.mp3"}
  ]
}
```

Paths are resolved relative to the service working directory (repo root).
On the next publish, ffmpeg will swap the original audio track for this
one. The output is cached next to the source video as
`<filename>.replace_audio.mp4` — re-runs for the same input hit the cache.

Optional: override the AAC bitrate (default `128k`):

```json
{"name": "replace_audio", "audio_path": "...", "bitrate": "192k"}
```

## Testing a track locally before deploying

```bash
ffmpeg -y -i sample_clip.mp4 \
  -stream_loop -1 -i brand/audio/nmahya_bgm.mp3 \
  -map 0:v:0 -map 1:a:0 \
  -c:v copy -c:a aac -b:a 128k -shortest \
  /tmp/out.mp4
```

Play `/tmp/out.mp4` and confirm the track fits the clip's tone before
rolling it out to production.
