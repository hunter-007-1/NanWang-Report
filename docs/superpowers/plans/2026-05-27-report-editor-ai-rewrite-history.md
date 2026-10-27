# Report Editor AI Rewrite History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the AI rewrite and history rollback controls from `dianwang_report_gen/frontend` in the integrated `frame_fore-end_design` report editor.

**Architecture:** Keep `frame_fore-end_design` as the integrated static frontend served by `powergrid_pipeline/bridge_server.py`. Port only the missing report editor UI/state/API wiring, while preserving the integrated frontend default API base URL. Add Flask proxy routes for the already-existing report API endpoints.

**Tech Stack:** Static HTML/CSS/JavaScript, Flask bridge server, FastAPI report app imported through ASGI transport.

---

### Task 1: Static Regression Check

**Files:**
- Create: `tests/test_frame_report_editor_features.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_integrated_report_editor_contains_ai_rewrite_and_history_ui():
    html = read_text("frame_fore-end_design/report_editor.html")
    css = read_text("frame_fore-end_design/report_editor.css")
    js = read_text("frame_fore-end_design/report_editor.js")

    assert 'id="versions-btn"' in html
    assert 'id="versions-panel"' in html
    assert 'id="version-preview-modal"' in html
    assert 'id="rewrite-selection-meta"' in html
    assert 'id="rewrite-instruction"' in html
    assert 'id="rewrite-generate-btn"' in html
    assert 'id="rewrite-apply-btn"' in html
    assert 'id="rewrite-result"' in html
    assert ".versions-card" in css
    assert ".rewrite-demo" in css
    assert "async function onGenerateRewriteSuggestion" in js
    assert "async function rollbackReportVersion" in js
    assert "async listReportVersions" in js
    assert "async rewriteSelection" in js
    assert 'reason: "rewrite"' in js


def test_bridge_server_proxies_report_editor_feature_routes():
    bridge = read_text("powergrid_pipeline/bridge_server.py")

    for route in [
        '"/api/reports/versions"',
        '"/api/reports/versions/read"',
        '"/api/reports/versions/rollback"',
        '"/api/reports/versions/delete"',
        '"/api/reports/rewrite"',
    ]:
        assert route in bridge
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_frame_report_editor_features.py -q`
Expected: FAIL because `frame_fore-end_design/report_editor.html` lacks `versions-btn` and rewrite controls.

### Task 2: Port Frontend Feature Wiring

**Files:**
- Modify: `frame_fore-end_design/report_editor.html`
- Modify: `frame_fore-end_design/report_editor.css`
- Modify: `frame_fore-end_design/report_editor.js`

- [ ] **Step 1: Add the missing history and rewrite markup**

Copy the history panel, preview modal, and AI rewrite block structure from `dianwang_report_gen/frontend/report_editor.html` into the matching locations in `frame_fore-end_design/report_editor.html`. Keep existing accessibility attributes on the mode buttons.

- [ ] **Step 2: Add the missing styles**

Copy the `.versions-*`, `.version-preview-*`, `.rewrite-*`, and `button.danger` rules from `dianwang_report_gen/frontend/report_editor.css` into `frame_fore-end_design/report_editor.css` without changing the existing visual theme.

- [ ] **Step 3: Add the missing JavaScript behavior**

Port the missing state fields, DOM references, event handlers, version functions, rewrite functions, and `RealReportApiClient` methods from `dianwang_report_gen/frontend/report_editor.js`. Preserve `getDefaultApiBaseUrl()` in `frame_fore-end_design/report_editor.js` so local static preview still targets `http://127.0.0.1:8080`.

### Task 3: Add Bridge Proxies

**Files:**
- Modify: `powergrid_pipeline/bridge_server.py`

- [ ] **Step 1: Add proxy routes**

Add Flask route handlers next to the existing `/api/reports/*` proxies for versions list/read/rollback/delete and rewrite. Use `proxy_report_api` with `method="GET", forward_body=False` for the versions list route and default POST forwarding for the others.

### Task 4: Verify

**Files:**
- Test: `tests/test_frame_report_editor_features.py`

- [ ] **Step 1: Run the regression check**

Run: `python -m pytest tests/test_frame_report_editor_features.py -q`
Expected: PASS.

- [ ] **Step 2: Run syntax checks**

Run: `node --check frame_fore-end_design/report_editor.js`
Expected: no output and exit code 0.

Run: `python -m py_compile powergrid_pipeline/bridge_server.py`
Expected: no output and exit code 0.
