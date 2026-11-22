# poster-maker

Turn your own photos into print-ready retro posters (paper texture, film grain, giant title, info row, crop marks and a QR code) with one command.

```bash
uv sync
uv run python poster.py config/poster.toml   # -> output/retro_classic_A4.png (2480x3508, 300 DPI)
```

Put your photo in `photos/` and point `photo` in `config/poster.toml` at it.

See [HANDOUT.md](HANDOUT.md) for the concepts, the exercises and troubleshooting.

## Fonts

Static fonts are in `fonts/` (SIL Open Font License, licences included): Jost ExtraBold, Inter Bold and IBM Plex Mono Regular. Jost and Inter are instanced from the Google Fonts variable files with fontTools.
