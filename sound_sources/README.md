# Engine sound sources (not shipped)

Real recordings that `process_recordings.py` turns into the engine loops (`generate_sounds.py` calls it).
Only CC0 and CC-BY recordings are used, never NonCommercial ones, so the mod can be published under any licence. Credits go to `GameData/ROPlanesPlus/Sounds/CREDITS.txt` automatically.

- `previews/<freesound id>.ogg`: Freesound "HQ preview" (~192 kbps Ogg). These can be downloaded without an account from `https://cdn.freesound.org/previews/<first 3 digits>/<id>_<user id>-hq.ogg`.
- `originals/<freesound id>.<ext>`: full-quality downloads, which need a free Freesound login. When a file is present here it is used instead of the preview. Every source the recipes use has its original here (downloaded on 2026-11-17), so the previews are only a fallback now. The Wilga (140436) original is an MP3, which is how it was uploaded. The old radial sources (437838 C-47, 437863 four-engine, 143559 B-25) are no longer used; they were multi-engine and carried the beat of unsynchronised engines.

The loops actually built from each file are listed in `RECIPES` in `process_recordings.py`. The other previews here were candidates that were analysed and not chosen (Doppler fly-bys, interior recordings, noisy multi-engine clips). They are kept for future tuning.

Analysing a candidate: find a steady section (constant level and pitch). Identify the engine's cycle frequency, the 0.5-order harmonic grid = rpm / 120, from the harmonic series. A propeller's blade-pass line is the best cross-check: blades × prop rpm, through the reduction gear. Firing frequency = cylinders × cycle frequency.
