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

# AGENTS.md

## AI Context
- Before broad project analysis, read `AI_CONTEXT/00_project_overview.md` first.
- Then select only the relevant files from `AI_CONTEXT/01_architecture.md` through `AI_CONTEXT/06_current_status.md`.
- For code changes, use `AI_CONTEXT/03_module_map.md` to narrow source reads and `AI_CONTEXT/05_test_guide.md` for verification.
- After a material architecture, data-flow, business-rule, test, or status change, update the corresponding AI context file and append `AI_CONTEXT/07_change_log.md`.

## Workspace Shape
- This repo is a workspace with multiple subprojects, not a single app.
- Root overview:
  - `powergrid_pipeline/`: main integrated demo backend; current end-to-end entrypoint.
  - `frame_fore-end_design/`: static frontend demo used by `powergrid_pipeline/bridge_server.py`.
  - `dianwang_report_gen/`: separate report-generation app with its own `AGENTS.md`; read that file before changing anything there.

## Use These Entry Points
- End-to-end demo entrypoint: `cd powergrid_pipeline && python bridge_server.py`
- Direct algorithm run: `cd powergrid_pipeline && python powergrid_pipeline_v2/functional_tests/main_scc.py <base_model.dat> [target_count]`
- Static frontend only: `cd frame_fore-end_design && python -m http.server 5173`

## Runtime Constraints
- The power-grid pipeline is effectively Windows-only for real runs.
- Real backend runs need local DSP/BPA installation and `pybpa`; configure `DSP_BIN_DIR` and `MODELSCOPE_API_KEY` in the local environment.
- Important settings to verify before backend work:
  - `paths.dsp_bin_dir`
  - `api.modelscope_api_key`
  - `api.modelscope_base_url`
  - `api.llm_model_name`

## Non-Obvious Wiring
- `powergrid_pipeline/bridge_server.py` serves `../frame_fore-end_design` as its static frontend on `http://127.0.0.1:8080`.
- `bridge_server.py` does not just proxy the report app over HTTP; it imports `../dianwang_report_gen/main_api.py` directly and exposes its routes under:
  - `/api/compare-reports`
  - `/api/reports/*`
- When using `bridge_server.py`, treat it as the unified backend for both planning and report APIs.

## Inputs And Outputs
- `POST /api/files/upload` stores uploaded files under `powergrid_pipeline/powergrid_pipeline_v2/data_test/`.
- `main_scc.py` also reads:
  - `PROGRESS_FILE`
  - `TARGET_SCHEME_COUNT`
- Planning run outputs are written under `powergrid_pipeline/fulfillment_scc/run_*`.
- Task logs/progress are written under `powergrid_pipeline/powergrid_pipeline_v2/logs/task_*/`.

## Verification Reality
- There is no root CI, formatter, linter, typecheck, or pre-commit config to rely on.
- `powergrid_pipeline/powergrid_pipeline_v2/functional_tests/` are mostly runnable scripts with `run_test()` / `if __name__ == "__main__"` patterns, not a clearly wired pytest suite.
- Do not assume `pytest` is the real verification path for `powergrid_pipeline`; inspect the specific script you are touching.

## Frontend Gotcha
- `frame_fore-end_design/app.js` defaults to real backend mode: `useMockBackend: false`.
- Mock/real switching is controlled by URL params like `?mock=0`, `?mock=1`, and `?compareReal=0`.

## Worktree Noise
- Running the pipeline creates untracked generated output under `powergrid_pipeline/fulfillment_scc/`. Do not treat that directory as hand-authored source.
