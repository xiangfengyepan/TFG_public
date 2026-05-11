/* eslint-disable */
/*
 * Boot script injected into gephi-lite's index.html BEFORE the React bundle.
 * Reads ?repo=<id> and ?layout=<radial|hierarchical> from the URL,
 * writes 1.0_session (layout) into sessionStorage, and points gephi-lite
 * at the right pre-filtered GEXF via the ?file= URL parameter.
 *
 * The build script (deploy/build.ps1) replaces the placeholder tokens
 * below with real values at build time.
 */
(function () {
  "use strict";

  // ── Injected at build time ─────────────────────────────────────────────────
  var SESSIONS = {
    radial:        /*__SESSION_RADIAL__*/        null,
    hierarchical:  /*__SESSION_HIERARCHICAL__*/  null
  };
  // Map of repo id -> GEXF filename (relative to this page).
  // Built from the contents of repo_graph/exports/.
  var REPO_GEXF = /*__REPO_GEXF_MAP__*/ {};
  // Filename used when no ?repo= is given (the full graph).
  var DEFAULT_GEXF = /*__DEFAULT_GEXF__*/ "swe_bench_graph.gexf";

  // ── URL params ─────────────────────────────────────────────────────────────
  var params = new URLSearchParams(window.location.search);
  var repo   = params.get("repo");
  var layout = params.get("layout") || "radial";

  // ── Apply layout (1.0_session) ─────────────────────────────────────────────
  if (SESSIONS[layout]) {
    try {
      sessionStorage.setItem("1.0_session", JSON.stringify(SESSIONS[layout]));
    } catch (e) {
      console.warn("[repo-graph boot] failed to write 1.0_session:", e);
    }
  }

  // Make sure no stale filter from a previous visit interferes — the
  // pre-filtered GEXFs already represent the subset the user asked for.
  try { sessionStorage.removeItem("1.0_filters"); } catch (e) {}

  // ── Pick the GEXF file ─────────────────────────────────────────────────────
  // Normalise: accept both "repo_OpenHands" and "OpenHands".
  var gexfFile = DEFAULT_GEXF;
  if (repo) {
    var key = repo.indexOf("repo_") === 0 ? repo : "repo_" + repo;
    if (Object.prototype.hasOwnProperty.call(REPO_GEXF, key)) {
      gexfFile = REPO_GEXF[key];
    } else {
      console.warn("[repo-graph boot] unknown repo '" + repo + "', falling back to full graph");
    }
  }

  // ── Tell gephi-lite to auto-fetch the GEXF (?file=…) ──────────────────────
  if (!params.has("file")) {
    var gexfUrl = new URL("./" + gexfFile, window.location.href).href;
    params.set("file", gexfUrl);
    var newUrl = window.location.pathname + "?" + params.toString() + window.location.hash;
    // Replace the URL synchronously without reloading; gephi-lite's
    // Initialize.tsx reads window.location.href after this script returns.
    window.history.replaceState(null, "", newUrl);
  }
})();
