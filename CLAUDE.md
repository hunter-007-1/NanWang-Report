<!-- LORE:START -->
## Lore (auto-managed)

Project memory. Read deeper on demand.

**Structure**:
- Digest: `.lore/SUMMARY.md` (top-level overview)
- Global: `.lore/_global/` (architecture, decisions, conventions)
- Scopes: `.lore/scopes/`
  - `.lore/scopes/dianwang_report_gen/`
  - `.lore/scopes/frame_fore-end_design/`
  - `.lore/scopes/powergrid_pipeline/`

**Query**: `lore query <term>` or `lore query <scope>:<term>`
**Update**: see the `lore` skill (init / sync / query / audit / compress / mirror)
<!-- LORE:END -->

---

## My notes (free edit)

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Structure

This is a **workspace** containing two independent subprojects:

- `powergrid_pipeline/` — End-to-end power grid planning demo (Flask backend + static frontend)
- `dianwang_report_gen/` — Standalone AI report generation app with its own `CLAUDE.md`
- `frame_fore-end_design/` — Static frontend demo, served by `bridge_server.py`

## Entry Points

| Command | Description |
|---------|-------------|
| `cd powergrid_pipeline && python bridge_server.py` | Full stack demo (frontend + backend planning + report APIs) |
| `cd powergrid_pipeline && python powergrid_pipeline_v2/functional_tests/main_scc.py <model.dat> [n]` | Algorithm only, no UI |
| `cd frame_fore-end_design && python -m http.server 5173` | Frontend only (mock mode) |

Bridge server listens on `http://127.0.0.1:8080` and serves the frontend directly.

## Key Constraints

- **Windows-only for real pipeline runs.** The algorithm uses DSP/BPA simulation tools via `pybpa`; `settings.yaml` contains Windows-style paths.
- **Must configure before running:** `powergrid_pipeline/powergrid_pipeline_v2/config/settings.yaml` — at minimum: `paths.dsp_bin_dir`, `api.modelscope_api_key`, `api.modelscope_base_url`, `api.llm_model_name`.
- **No CI/linter/formatter.** Functional tests use `run_test()` / `if __name__ == "__main__"` patterns, not pytest.

## Architecture Notes

**`bridge_server.py`** wires three things together:
1. Serves `frame_fore-end_design/` as static files
2. Spawns `main_scc.py` for planning tasks
3. Imports `dianwang_report_gen/main_api.py` directly and exposes its routes (`/api/compare-reports`, `/api/reports/*`)

**Pipeline flow:** Upload model → initial simulation (power flow, N-1, short circuit) → LLM generates schemes → apply schemes → evaluate → frontend displays results.

**Outputs land under** `powergrid_pipeline/fulfillment_scc/run_*/` (generated, not hand-authored).

## Working Across Subprojects

- Before modifying anything in `dianwang_report_gen/`, read its own `CLAUDE.md` first.
- `dianwang_report_gen/` has its own conda environment, dependencies, and entry points — do not assume shared state with `powergrid_pipeline/`.
- Frontend mock/real mode is controlled by URL params: `?mock=0`, `?mock=1`, `?compareReal=0`.
