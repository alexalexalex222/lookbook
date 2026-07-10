# Shared-Atoms Candidates — clear_ridge_water_works_field_blue_v1

Seven reusable atoms are implemented in `source_snapshot/` (HTML + CSS, plus vanilla JS where interactive). All are self-contained, image-free, accessible, and proof-safe. Locations are given as `file:selector` so they can be lifted cleanly.

| Atom | Where (HTML) | CSS hook | JS | Reusable for |
| --- | --- | --- | --- | --- |
| `diagnostic_issue_selector_v1` | `index.html` `section#diagnose .diagnostic` (`.issue-tabs[role=tablist]` + `.issue-readout`) | `styles.css` `.diagnostic`, `.issue-tab`, `.issue-readout`, `.urgency-pill` | `script.js` tabs block (WAI-ARIA roving tabindex, arrow/Home/End) | Any "pick your symptom -> read likely cause" instrument: HVAC, appliance repair, IT/network triage, auto, medical-intake-style selectors. |
| `field_service_quote_flow_v1` | `index.html` `form#quote-form` | `styles.css` `.quote-form`, `.field`, `.field-error`, `.radio`, `.form-success` | `script.js` validation block | Any trade/service quote or intake: labelled fields, inline validation, live status, focus-managed success, never-lose-input. |
| `service_area_map_shell_v1` | `index.html` `section#area .area-map` + `.area-card` | `styles.css` `.area-map`, `.area-card`, `.area-placeholder`, `.area-facts` | none | Any local service that must show coverage **without** inventing locations — region concept + `[SERVICE_AREA_TOWNS]` placeholder. |
| `equipment_diagram_svg_v1` | `index.html` `figure.system-diagram svg` + `ol.system-legend` | `styles.css` `.system-diagram`, `.system-legend`, `.diagram-label` | none (CSS `wave-drift` only) | Any "how the system works" cutaway: HVAC loop, plumbing stack, solar/battery, irrigation, pool equipment, with numbered legend. |
| `emergency_vs_planned_panel_v1` | `index.html` `section#service .split-grid` (`.split-emergency` / `.split-planned`) | `styles.css` `.split-card`, `.split-emergency`, `.split-planned`, `.split-list` | none | Any service that splits urgent vs scheduled work with honest triggers and next steps (no fake response time). |
| `maintenance_plan_comparison_v1` | `index.html` `section#plans .plans-grid` (`.plan-card`, `.plan-featured`, `.plan-addon`) | `styles.css` `.plans-grid`, `.plan-card`, `.plan-featured`, `.plan-flag`, asymmetric grid in the `min-width:960px` block | none | Plan/tier comparison that needs **real hierarchy** instead of three equal cards: featured (dark, lifted) + baseline + dashed add-on. |
| `proof_safe_service_record_v1` | `index.html` `section#record .record-grid` (`.record-card.is-placeholder` + `.record-note`) | `styles.css` `.record-card`, `.record-flag`, `.record-note` | none | Any "track record / past work" surface that must stay honest — ships the entry *format* as labeled placeholders, never invented jobs/reviews/counts. |

## Promotion notes
- **Token coupling**: all atoms read from the shared `:root` token set (color roles, `--fs-*`, `--sp-*`, radii, motion). When promoting an atom to a shared library, lift the token subset it uses (each atom's CSS references roles, not raw hex, except inside SVG fills which use `var(--...)`).
- **Dark-surface pairs**: `diagnostic_issue_selector_v1`, the quote section wrapper, `plan-featured`, the region map, and `record-note` share the dark field-blue surface tokens (`--dark-bg`, `--dark-panel`, `--dark-line`, `--dark-ink*`). Keep them together for visual consistency, or pass surface as a modifier.
- **JS isolation**: the two interactive atoms degrade gracefully — without JS the tabs show the first panel and the form is still a valid, labelled, submittable HTML form. Safe to adopt independently; the `script.js` IIFE guards each block with element-presence checks.
- **Proof policy travels with the atom**: `service_area_map_shell_v1`, `proof_safe_service_record_v1`, and `maintenance_plan_comparison_v1` carry labeled placeholders and proof-safe copy. Do not strip them when reusing.

## Candidate atom-dir layout (if promoted, matching `*/atoms/` convention)
```
atoms/
  diagnostic_issue_selector/   { markup.html, styles.css, behavior.js, notes.md }
  field_service_quote_flow/    { markup.html, styles.css, behavior.js, notes.md }
  service_area_map_shell/      { markup.html, styles.css, notes.md }
  equipment_diagram_svg/       { markup.html, styles.css, notes.md }
  emergency_vs_planned_panel/  { markup.html, styles.css, notes.md }
  maintenance_plan_comparison/ { markup.html, styles.css, notes.md }
  proof_safe_service_record/   { markup.html, styles.css, notes.md }
```
Not split out in this pack to keep the source snapshot a single coherent page (matching the reference pack); the table above is the extraction map.
