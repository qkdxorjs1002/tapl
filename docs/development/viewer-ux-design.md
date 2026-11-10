# Viewer and extension UX design and upgrade plan

**English** · [한국어](viewer-ux-design.ko.md)

**This is a design proposal. [Viewer](../guides/viewer.md) and [VS Code extension](../guides/vscode.md) describe current product behavior.**

## Integrated concept

The [integrated Viewer concept](../design/viewer-workbench/index.html) combines the current-work focus of 03 with the TASK status view of 01 in a fixed shell. Screenshots show [current RUN](../design/viewer-workbench/current-ko.png), [Explore details](../design/viewer-workbench/explore-ko.png), [integrated search](../design/viewer-workbench/search-ko.png) and [English with a dark theme](../design/viewer-workbench/current-en-dark.png).

| Area | Structure and behavior |
| --- | --- |
| Fixed top bar | RUN navigation tabs use the available space, showing title, status and ID without session labels. Switching changes status, Explore and management context to the selected RUN. Arrow keys, Home and End are supported; excess tabs scroll within the tab region. |
| Upper-left Workspace | Current RUN uses the focus layout from 03, with a rounded integer percentage of completed / total TASKs at the right of its menu item (0% when there are no TASKs). TASK status uses a full-width list based on 01. Selecting a TASK opens its Explore detail page directly and synchronizes the fold and selected item. Page switching is provided only through the sidebar; page tabs and breadcrumbs are omitted. |
| Upper-left Explore | At most one PLAN, TASK or FINDING fold is open. Its list scrolls independently and retains its position per RUN and kind. Selecting a record displays its objective, requirements, verification, results, related records and extra fields in the page rather than a popup. |
| Lower-left Memory | Open record search or associative memory. Record search combines PLAN, TASK and FINDING with independent `Selected RUN / All records` scopes and `Group by RUN / Record list` presentation. Associative memory retains read-only workspace lessons, cues and source browsing. |
| Lower-left Management | `Discard RUN` retains existing semantics: RUNs with records are archived, empty RUNs can be deleted, and confirmation requires the exact RUN ID. The control follows server discard support and RUN `writable`; writable local RUNs from other sessions remain eligible. Read-only peer history disables it. Discard does not stop external agents or processes. **The concept's confirmation button deletes neither real RUNs nor synthetic data.** |

On PC, the top bar and sidebar remain fixed while only the right page scrolls. The expanded Explore list is a separate scroll region. Narrow layouts expose navigation through a menu and exclude the closed panel from keyboard navigation. Each RUN keeps separate page, search and record selection state. Selecting another RUN's search result or memory source moves to its source RUN tab. The examples include identical display IDs with distinct provenance.

TASK status and PLAN/TASK/FINDING tabs display counts with units: `12개` in Korean and `12 items` (`1 item` for singular) in English.

The header uses the `tapl` name as text. Pages opened through internal links show a `Back` button at the upper right. TASKs, search results, related records and memory sources can return to the previous RUN, page, query/filter, expanded groups, selected record and scroll position. The current language and theme remain in effect. Choosing a sidebar page or top RUN tab directly starts a new navigation path and clears the return trail. Direct links and reloaded pages have no return button.

Grouped search across all records shows RUN titles, provenance and match counts first; expand a group to read individual records. Expanded groups persist through language and theme changes. Record-list presentation lists individual records directly.

Switch Korean/English UI, status, guidance, accessible labels and sample content, as well as light/dark themes. Locale switching does not promise automatic translation of stored records. Product implementation must retain locale delivery, existing translation keys and user-authored content as separate concerns. Links can specify context, for example `#run=local24&page=tasks&lang=en&theme=dark`.

Screens retain titles, status, record content and necessary provenance while omitting generic introductions, demo badges, repeated footers and duplicate context. Grouped search places provenance in group headers; record-list presentation shows it per result. Empty-state help and discard confirmation/effect descriptions remain where needed.

The light theme combines cool gray and white surfaces with a deep teal accent; the dark theme uses navy surfaces and a pale teal accent. Larger body and secondary text, increased line height, thin dividers and restrained shadows establish hierarchy. The RUN indicator and page transition take 260ms; folds and search groups take 180–240ms. Rapid input settles interrupted motion. `prefers-reduced-motion` removes motion, and theme colors switch immediately.

This is an independent synthetic concept before product integration. Existing CLI/MCP arguments, configuration, VS Code host behavior and RUN discard are unchanged. The ten alternatives below remain available for comparing individual information structures.

The integrated concept was checked in headless Chrome with a temporary profile: two locales × two themes × four widths (320, 390, 1024 and 1600px) × five pages, totaling 80 combinations. No horizontal overflow, sidebar clipping or script errors were found. Twenty-two body/secondary text and primary button color pairs had a minimum contrast of 4.64:1. Checks also covered 16 locale/width/RUN combinations for TASK-to-Explore navigation, retained filters, keyboard activation, visible selection, rapid RUN/fold/search-group switching and reduced motion. Back navigation was checked across 32 locale/theme/width return cases, plus query/filter, cross-RUN, related-record, memory-source, keyboard, scroll and focus restoration, and rapid returns during normal motion. Representative screens were visually reviewed. These checks do not replace actual VS Code host, high-contrast or screen-reader validation.

## Explore the concepts

Open the [gallery of ten concepts](../design/viewer-concepts/index.html) in a browser. It works without installation and uses local styles and scripts. GitHub's HTML source view does not run the preview; download the repository and open it locally.

An [overview image](../design/viewer-concepts/overview.png) is also available. The gallery's `#overview` fragment opens the comparison directly.

- Select a concept using the left navigation or previous/next buttons. Direct links use `#01` through `#10`.
- Compare paired, Viewer and extension previews in light and dark themes.
- Select normal, loading, empty or connection-error states.
- Task details, status filters, record search, memory sources and document navigation operate within the demo. Submit searches with Enter.
- Use the overview to compare all ten information structures.

RUNs, tasks, owners, records and timestamps are synthetic. The 2/6 completion count is comparison data and does not mean the actual upgrade is complete. The gallery separately builds **DaisyUI 5.7.50 / Tailwind CSS 4.3.5**. It changes no shipping package versions, settings, CLI/MCP arguments, execution, approval or discard behavior. The extension preview represents narrow webview content; it does not reproduce native VS Code Tree Views, the extension host or its CSP runtime.

## Findings from the current implementation

| Evidence | UX or maintenance effect | Proposed direction |
| --- | --- | --- |
| `OverviewView` places a large header, status pills and six metric cards before the task list. | Users scan aggregate information before current work and blockers. | Lead with RUN identity, current work and blockers; disclose other metrics progressively. |
| `App.tsx` combines routing, RUN tabs, the board, records and detail renderers. | Information-structure changes have a broad review surface. | Separate views, read models, components and host adapters. |
| CSS broadly overrides buttons, inputs, tabs, cards and `tapl-*` structures despite using DaisyUI. | Base components and custom presentation must be maintained together. | Prefer semantic tokens and variants; reserve dedicated CSS for layout. |
| `styles.css` already uses VS Code semantic colors, fonts and focus variables. | Losing this mapping would break editor-theme integration. | Preserve it in a DaisyUI 5 token adapter. |
| Browser and extension share React UI but receive updates differently. | Splitting views alone does not separate transport responsibilities. | Keep browser polling and extension push in adapters. |

Sources: [`App.tsx`](../../vscode-extension/src/webview/App.tsx), [`styles.css`](../../vscode-extension/src/webview/styles.css), [`MemoryView.tsx`](../../vscode-extension/src/webview/MemoryView.tsx), [`extension.ts`](../../vscode-extension/src/extension.ts), [`viewer.py`](../../tapl/taplctl/viewer.py). These are design judgments from code inspection, not usability-test findings or measured performance improvements.

## Ten directions

| Concept | Main information structure | Extension adaptation | Fit and limitation |
| --- | --- | --- | --- |
| **01 Signal Desk** | Task list alongside selected-task detail | Compact list and detail dialog | **Basis of the integrated TASK status view.** Balances work and evidence. |
| 02 Flow Board | Pending, running, blocked and completed lanes | Status filter and vertical lanes | Parallel work; long queues increase page length. |
| **03 Focus Now** | Current task, purpose, verification and next queue | Prioritize the current task | **Basis of the integrated current RUN view.** Needs a separate comparison view. |
| 04 Evidence Stream | Chronological events and source records | Vertical timeline | Resuming and retrospectives; chronology is not dependency order. |
| 05 Record Library | Search results alongside source content | Results followed by content | Records and archives; less suitable for live execution. |
| 06 Memory Garden | Lessons, recall cues and sources | Single-column memory cards | Dedicated memory screen; progressively disclose long content. |
| 07 Run Atlas | RUN cards with owners and sources | Vertical RUN list | Multiple sessions and peer history; excessive for a single RUN. |
| 08 Spec Explorer | TASK and FINDING navigation under PLAN | Navigation followed by content | Long plans and verification records; collapse deep hierarchies. |
| 09 Dependency Lens | Prerequisite and downstream TASK connections | Read conditions from top to bottom | Blocker analysis; graph layout requires separate implementation. |
| 10 Quiet Outline | Short outline, task list and collapsed records | Single-column progressive disclosure | Reading and keyboard use; needs an auxiliary comparison view. |

The integrated concept **combines 01 and 03 as Workspace pages**, uses 05 for search, 06 for memory and 08's information structure for record exploration. It does not add all ten as product view options. The dependency view from 09 remains an optional follow-up.

## DaisyUI component use

| Responsibility | Components | Composition principle |
| --- | --- | --- |
| Workspace and RUN navigation | `menu`, `dropdown`, `tabs` | Identify location and source; preserve selected state and arrow-key behavior. |
| TASK summaries and lists | `table`, v5 `list` / `list-row`, `card` | Tables for wide screens, lists for narrow screens; avoid turning every row into a card. |
| State and progress | `badge`, v5 `status`, `progress`, `steps` | Pair text with color, include actual states such as Skipped, and do not treat task completion percentage as a success verdict. |
| Search and filters | `input`, `select`, `join`, v5 `fieldset` | Provide labels and selected states; do not put essential actions only in tooltips. |
| Details and long records | `collapse`, `modal`, `tabs` | Reveal sources and extra fields on demand; support focus return and Escape. |
| Events and feedback | `timeline`, `alert`, `skeleton`, `loading` | Distinguish new data, loading, empty, error and stale-data states. |

The goal is not to add more components. Use the structures, states and sizes from the [official component library](https://daisyui.com/components/), keeping product CSS focused on layout, density and token adaptation. DaisyUI does not provide dependency graph layout; give layout and keyboard navigation a separate responsibility.

## Refactoring phases

### 1. Regression baseline and version transition

The shipping stack is DaisyUI 4.12.24 / Tailwind CSS 3.4.17 / React 18.3.1 / Vite 5.4.20. Capture fixtures for the current screens and host protocol first, then verify the **DaisyUI 5 + Tailwind CSS 4 transition** independently of information-structure changes. Pin selected patch versions in the product lockfile at implementation time. The gallery build does not validate the product migration.

1. Separate the old DaisyUI plugin configuration and move to the Tailwind 4 CSS entry point and `@plugin "daisyui"`. Do not copy v4 JavaScript settings unchanged.
2. Check Vite, Node and Tailwind plugin compatibility. Prefer evaluating `@tailwindcss/vite`; if compatibility requires retaining PostCSS, use `@tailwindcss/postcss`. Do not apply both paths. Validate any necessary Vite major upgrade in a separate diff.
3. Replace `@tailwind` entry directives with `@import "tailwindcss"`. Inspect generated JavaScript configuration, theme, `@apply` and dynamic status-class output.
4. Migrate actual uses of `tabs-boxed` → `tabs-box`, `card-bordered` → `card-border`, `card-compact` → `card-sm`, menu `active` → `menu-active`, and removed `input-bordered` and form-label classes.
5. Map the v4 theme to v5 semantic color, radius and size tokens. Connect `--vscode-*` as valid CSS colors rather than reusing old color-format conversions.
6. Check conflicts between `github-markdown-css`, Tailwind preflight, VS Code high-contrast themes and focus styles. Package local assets without external CDNs, fonts or scripts, and retain browser-asset synchronization.

Follow the [DaisyUI upgrade guide](https://daisyui.com/docs/upgrade/) and [Tailwind upgrade guide](https://tailwindcss.com/docs/upgrade-guide). The automated Tailwind upgrade tool requires Node.js 20+. The documented v4 browser baseline is Safari 16.4+, Chrome 111+ and Firefox 128+; also check additional CSS used by selected patch versions in the actual Chromium shipped by the lowest supported VS Code version. Do not raise the extension's minimum version without this check.

### 2. Separate shared UI responsibilities

The following modules are proposals, not existing APIs.

| Boundary | Responsibility |
| --- | --- |
| `model/` | Read models, sorting and filtering for RUNs, TASKs, dependencies, sources and capabilities |
| `transport/` | Browser polling and VS Code message adapters, cancellation, errors and freshness |
| `components/` | `RunIdentity`, `StatusBadge`, `TaskList`, `TaskDetail`, `RecordContent`, `EmptyState` |
| `views/` | Overview, Records, Memory, Workspace and Debug composition |
| `theme/` | Browser and VS Code token adapters, density and contrast |

Avoid implementing the same task information twice across surfaces. Separate responsibilities while retaining existing presentation, then apply the selected layout. Preserve `auto/small/medium/large`, Korean and English, custom fields, Markdown, execution timing and batch/execution details.

### 3. Apply the selected UX

- Lead with RUN identity, purpose, current TASK and blockers. Select at most two or three useful metrics and move Debug, source content and extra fields into details.
- Read task purpose, owner, prerequisites, verification and result through one consistent detail component.
- Recompose according to width: current-task focus in narrow extensions, a single list at medium width, and list/detail composition in wide containers. Use webview container width rather than viewport width.
- Preserve `(source_db, id)` identity, session ownership and capabilities across multiple RUNs. Keep browsing and execution authority distinct.
- Preserve selection, expansion, input, scrolling and focus through refresh. Design empty-RUN, loading, connection-error and stale-data states.
- Retain capability gating and exact-ID confirmation for RUN discard. The gallery does not implement discard.

### 4. Verify before adoption

These are completion criteria for subsequent product implementation.

- Check light, dark and high-contrast themes, narrow containers, and long Korean, English and Markdown content in browsers and actual VS Code webviews.
- Preserve information for no RUN, multiple RUNs, peer history, many TASKs, every TASK state, parallel batches, errors and details opened during refresh.
- Verify RUN-tab keyboard navigation, selected TASKs, dialog focus and Escape, and scroll/focus after automatic updates. Pair text with color and target 4.5:1 body-text contrast.
- Retain existing CLI/MCP arguments, configuration defaults and read-only behavior. Review necessary changes as explicit user behavior and update bilingual user guides together.
- Run a short usability check for locating current work, blockers and sources. Report improvements only after measuring them.

```sh
npm --prefix vscode-extension run compile
npm --prefix vscode-extension run test:host
uv --directory tapl run --extra test python -m pytest -q tests/test_viewer.py tests/test_viewer_native.py tests/test_viewer_discard.py tests/test_viewer_readonly.py tests/test_viewer_sources.py tests/test_run_discard.py
git diff --check
```

These commands apply to the subsequent product refactor. Run related session, read-only and recall tests and actual webview checks according to the changed boundaries. Commit the version transition and UI changes separately so previous builds, lockfiles and shared assets remain available for rollback.

## Maintain the gallery

Run from the repository root. Generated `components.css` is included, so viewing requires no installation. The integrated concept shares this local CSS; `build` and `check` cover both concepts.

```sh
npm --prefix docs/design/viewer-concepts ci
npm --prefix docs/design/viewer-concepts run build
npm --prefix docs/design/viewer-concepts run check
python3 -m http.server 8767 --bind 127.0.0.1 --directory .
```

When serving, open `http://127.0.0.1:8767/docs/design/viewer-concepts/`. Opening `index.html` directly also works. Edit `components.source.css`, `concepts.js` and `lab.css`. Screen copy is Korean; both language guides link to the same gallery.

Open the integrated concept at `http://127.0.0.1:8767/docs/design/viewer-workbench/`. Its editable sources are `viewer-workbench/index.html`, `workbench.js` and `workbench.css`. Switch Korean/English in its top bar.

The pinned minified build currently emits two optimizer warnings for selectors inside DaisyUI `join`'s `@scope`. Generation succeeds and the gallery supplies an explicit focus outline. Recheck these warnings and selector/focus rendering in the lowest supported webview during the product upgrade.

Gallery checks used headless Chrome with a temporary profile: 320, 390, 640, 1024 and 1600px × ten concepts × light/dark × three surface combinations, totaling 300 combinations and 30 additional states. These checks found no page/product horizontal overflow, script errors or external requests; filters, search, details, document selection and focus return were exercised. Representative screens were also visually inspected. This does not replace actual VS Code webview, high-contrast, screen-reader or usability validation.

Related: [Architecture](architecture.md) · [Contributing](contributing.md) · [Viewer](../guides/viewer.md) · [Extension](../guides/vscode.md) · [Documentation home](../README.md)
