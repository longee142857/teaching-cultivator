# HANDOFF (placeholder)

The real delivery-pack `HANDOFF.md` is not in this tree yet (see `MISSING_ASSETS.md`). When the tarball lands, replace this file; **do not invent merge steps**.

## Do not execute from this PR

- Do not change `KB_PATH`, cultivate, RAG, or `data/teaching.db`.
- Do not deploy or sync teaching cloud.
- Do not implement the `zhou_sqlite` backend until 恒宇 nods.

## After 恒宇 nods (outline only; real steps live in the pack)

1. Keep this directory read-only delivery.
2. Add a dedicated sqlite backend (name: `zhou_sqlite`) behind existing retrieval interfaces — do not bypass cultivate gates.
3. Re-run pack-local smoke (`python query_api.py demo`) before any wiring.
4. Treat L3 gap `comm.analog_mod.nbfm` as known, not as a silent miss.
