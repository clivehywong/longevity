"""
Minimal standalone Streamlit page for Papaya viewer end-to-end testing.

Uses locally-bundled papaya.js/css from tests/e2e/fixtures/ for offline and
CI reliability. Renders a small synthetic NIfTI test fixture so the test
does not depend on any real subject data.

Run standalone:
    streamlit run tests/e2e/papaya_test_page.py --server.port 8501
"""
import base64
from pathlib import Path

import streamlit as st

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_NIFTI = FIXTURE_DIR / "test_brain.nii"
PAPAYA_JS = FIXTURE_DIR / "papaya.js"
PAPAYA_CSS = FIXTURE_DIR / "papaya.css"

st.set_page_config(page_title="Papaya E2E Test", layout="wide")
st.title("Papaya Viewer E2E Test")
st.markdown("### Brain Volume Viewer")
st.markdown("*Synthetic 20×20×20 NIfTI fixture, 2 mm isotropic*")

if not TEST_NIFTI.exists():
    st.error(f"❌ Test NIfTI fixture not found: {TEST_NIFTI}")
    st.stop()

if not PAPAYA_JS.exists():
    st.error(f"❌ papaya.js not found — run: cd tests/e2e && python -c \"import urllib.request; urllib.request.urlretrieve('...')\"")
    st.stop()

with open(TEST_NIFTI, "rb") as fh:
    nii_b64 = base64.b64encode(fh.read()).decode("utf-8")

with open(PAPAYA_JS) as fh:
    papaya_js_content = fh.read()

with open(PAPAYA_CSS) as fh:
    papaya_css_content = fh.read()

# Build self-contained Papaya HTML (no external CDN dependency).
# Uses params["images"] with a data-URI so Papaya decodes via atob().
html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>{papaya_css_content}</style>
  <style>
    html, body {{ margin: 0; padding: 0; background: #1a1a1a; overflow: hidden; }}
    #papaya-status {{
      position: fixed; top: 6px; right: 6px;
      background: rgba(0, 140, 0, 0.85); color: #fff;
      padding: 3px 8px; font-size: 11px; border-radius: 3px;
      font-family: monospace; z-index: 9999;
    }}
  </style>
</head>
<body>
  <div id="papaya-status">Initializing Papaya...</div>
  <div id="papayaViewer" class="papaya" style="width:100%; height:490px;"></div>

  <script>
    /* Papaya viewer library — bundled locally for offline reliability */
    {papaya_js_content}
  </script>
  <script>
    (function() {{
      // params["images"] accepts data-URIs; Papaya decodes via atob()
      var params = [];
      params["images"] = [
        "data:application/octet-stream;base64,{nii_b64}"
      ];

      papaya.Container.addViewer("papayaViewer", params, function() {{
        document.getElementById("papaya-status").innerText = "Papaya viewer created";
      }});

      // Poll until the viewer fully initialises the NIfTI
      var maxWait = 15000;
      var waited  = 0;
      var poll = setInterval(function() {{
        waited += 250;
        var containers = (typeof papayaContainers !== "undefined") ? papayaContainers : [];
        if (containers.length > 0 && containers[0].viewer && containers[0].viewer.initialized) {{
          document.getElementById("papaya-status").innerText = "Papaya loaded \u2713";
          clearInterval(poll);
        }} else if (waited >= maxWait) {{
          document.getElementById("papaya-status").innerText = "Papaya timeout \u26a0";
          clearInterval(poll);
        }}
      }}, 250);
    }})();
  </script>
</body>
</html>"""

st.components.v1.html(html, height=510, scrolling=False)
st.success("✅ Papaya component HTML injected into iframe")
st.caption(f"Fixture: {TEST_NIFTI.name} — {TEST_NIFTI.stat().st_size:,} bytes")
