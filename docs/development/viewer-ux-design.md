# Viewer and extension UX design and upgrade plan

**English** · [한국어](viewer-ux-design.ko.md)

**The integrated layout is implemented in the shared Viewer; the galleries remain synthetic design references. [Viewer](../guides/viewer.md) and [VS Code extension](../guides/vscode.md) describe current product behavior.**

## Integrated concept

The [integrated Viewer concept](../design/viewer-workbench/index.html) combines RUN context and PLAN summaries, the Flow kanban of 02 and the TASK status view of 01 in a fixed shell. Screenshots show [current RUN](../design/viewer-workbench/current-ko.png), [Explore details](../design/viewer-workbench/explore-ko.png), [Explore flyout](../design/viewer-workbench/explore-panel-ko.png), [integrated search](../design/viewer-workbench/search-ko.png) and [English with a dark theme](../design/viewer-workbench/current-en-dark.png).

| Area | Structure and behavior |
| --- | --- |
| Fixed top bar | Language and light/dark icons align to the right of the `tapl` brand area. Open the language icon to choose 한국어 or English. RUN navigation tabs use the available space for unarchived RUNs, showing title, status and ID without session labels. Switching changes status, Explore and management context to the selected RUN. Arrow keys, Home and End are supported; excess tabs scroll within the tab region. |
| Upper-left Workspace | Current RUN combines RUN context, PLAN summaries and the Flow kanban, with a rounded integer percentage of completed / total TASKs at the right of its menu item (0% when there are no TASKs). TASK status uses a full-width list based on 01. Selecting a TASK opens its Explore detail page directly and synchronizes the exploration type and selected item. The sidebar switches between Current RUN and TASK status; duplicate page tabs and breadcrumbs are omitted. |
| Upper-left Explore | PLAN, TASK and FINDING show semantic icons and counts. On PC, hover or click opens one flyout to the right; it closes after the pointer leaves both trigger and panel. The list scrolls independently and preserves position per RUN and type. Selecting a record opens its page details. |
| Lower-left Memory | Open record search or associative memory. Record search combines PLAN, TASK and FINDING with independent `Selected RUN / All records` scopes and `Group by RUN / Record list` presentation. Associative memory retains read-only workspace lessons, cues and source browsing. |
| Lower-left Management | `Discard RUN` appears under the Management heading and retains existing semantics: RUNs with records are archived, empty RUNs can be deleted, and confirmation requires the exact RUN ID. The control follows server discard support and RUN `writable`; writable local RUNs from other sessions remain eligible. Read-only peer history disables it. Discard does not stop external agents or processes. **The concept's confirmation button deletes neither real RUNs nor synthetic data.** |

On PC, the top bar and sidebar remain fixed while only the right page scrolls. When height is limited, the sidebar itself scrolls vertically so Memory and Management remain reachable. The Explore flyout list scrolls independently. Narrow layouts expose navigation through a menu and exclude the closed panel from keyboard navigation. Each RUN keeps separate page, search and record selection state. Selecting another RUN's search result or memory source moves to its source RUN tab. Opening an archived RUN from record search or an associative memory source shows one temporary tab at the far right. Selecting another RUN tab removes it; RUNs already in the default tabs are not duplicated. The temporary tab persists through page, language and theme changes within that RUN, and follows the selected RUN on Back and direct links. Completion and archival are separate states. The examples include identical display IDs with distinct provenance.

The Explore flyout briefly delays pointer dismissal to allow crossing into the panel and does not shift the page layout. Open it with Enter, Space, Right or Down; navigate records with Up, Down, Home or End. Escape, Left and the close button return focus to the trigger; Tab can leave the panel. On narrow screens and touch devices, click within the menu to open an overlay fitted to the viewport, and click outside to dismiss it. Back from details restores focus to the exploration trigger on PC or to the menu button when the mobile menu is closed.

TASK status and PLAN/TASK/FINDING tabs display counts with units: `12개` in Korean and `12 items` (`1 item` for singular) in English.

Current RUN shows work type (`work_type`), difficulty, workflow mode (`workflow_mode`) and record mode (`record_mode`) at the top, each with an explanation. Labels and values occupy one compact row, with explanations in hover tooltips and accessible text. On narrow screens only the information row scrolls horizontally. PLAN and Task flow share section headings, card alignment, corners and spacing. Workflow mode describes review rigor and is separate from difficulty. Difficulty is an additional illustrative field in this concept; it does not change or connect to the shipping RUN schema.

PLAN summary cards show ID, status, title, a short objective and an arrow to the source. They occupy one row that scrolls horizontally when it exceeds the region. A single PLAN fills the region, and an empty state appears when none exist. Selecting a card opens its Explore PLAN source. Back restores card focus, page scroll and horizontal position. PLANs and task flow retain independent horizontal positions per RUN across language, theme and width changes.

Progress stages and phase-specific page switching are omitted. Existing `phase` links open the current TASK board. The TASK area consists of a blocker notice and the horizontal Flow kanban, with no separate current-task focus card. Pending, In progress, Blocked and Completed columns show counts with units, titles, owners and prerequisites in TASK ID order; skipped tasks get a separate column when present. Cards are read-only and open Explore details, with Back restoring page scroll and the original card focus. Status columns stay in one horizontal row at every width; scroll within the board to browse categories. A transparency gradient softens edges with remaining content, clearing at the corresponding start or end. Vertical movement uses page scrolling. The scroll region is keyboard accessible and restores its horizontal position across RUN, language and theme changes and Back. The carousel, Up next and Completed work lists are omitted.

The header uses the `tapl` name as text. Pages opened through internal links show a `Back` button at the upper right. TASKs, search results, related records and memory sources can return to the previous RUN, page, query/filter, expanded groups, selected record and scroll position. The current language and theme remain in effect. Choosing a sidebar page or top RUN tab directly starts a new navigation path and clears the return trail. Direct links and reloaded pages have no return button.

Record search defaults to all records and can be narrowed to the selected RUN. The search-scope selector shows a down arrow. RUN-grouped and record-list view controls share the status filter’s subtle pill outline. Grouped results start collapsed, showing RUN titles, provenance and match counts; expand a group to read individual records. Submitting a search, changing scope or resetting the search collapses the groups again. Manually expanded groups persist through language, theme and view changes and Back from details. Record-list presentation lists individual records directly.

Switch Korean/English UI, status, guidance, accessible labels and sample content, as well as light/dark themes. Locale switching does not promise automatic translation of stored records. Product implementation must retain locale delivery, existing translation keys and user-authored content as separate concerns. Links can specify context, for example `#run=local24&page=tasks&lang=en&theme=dark`.

Screens retain titles, status, record content and necessary provenance while omitting generic introductions, demo badges, repeated footers and duplicate context. The selected RUN is identified by the top tabs; Current RUN, TASK status and Explore detail headers omit repeated RUN ID, session and source rows. Grouped search places provenance in group headers; record-list presentation shows it per result. Empty-state help and discard confirmation/effect descriptions remain where needed.

The light theme combines cool gray and white surfaces with a deep teal accent; the dark theme uses navy surfaces and a pale teal accent. Larger body and secondary text, increased line height, thin dividers and restrained shadows establish hierarchy. The RUN indicator and page transition take 260ms; the Explore flyout takes 160ms and search groups take 180–240ms. Rapid input settles interrupted motion. `prefers-reduced-motion` removes motion, and theme colors switch immediately.

This synthetic concept is a design reference for the implemented shared Workbench. The product omits absent metadata, including the concept-only difficulty field. Public CLI arguments and configuration defaults remain unchanged; exact RUN reads and paginated record browsing use additive MCP tools. RUN discard retains its existing confirmation and lifecycle semantics. The ten alternatives below remain available for comparing individual information structures.

The integrated concept was checked in headless Chrome with a temporary profile across Korean/English, light/dark themes and 320, 390, 1024 and 1600px widths for RUN context, PLAN summaries and primary pages. Checks covered direct links, PLAN/TASK/FINDING source returns, focus, independent horizontal positions, page scroll, per-RUN state, read-only behavior, empty states, normal motion and reduced motion. Horizontal kanban checks covered wheel and keyboard input, fade boundaries and restoration after width changes. Explore checks covered pointer transitions, mixed input, keyboard, touch, responsive resizing and independent sidebar/list scrolling in short viewports. Twenty-two body/secondary text and primary button pairs in the base palette had a minimum contrast of 4.64:1. Representative screens were visually reviewed. These checks do not replace actual VS Code host, high-contrast or screen-reader validation.

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

| Boundary | Current implementation |
| --- | --- |
| Shared shell | `workbench/Workbench.tsx`, fixed desktop shell and responsive drawer |
| Navigation | `model.ts` and `useWorkbench.ts`, source-qualified RUN identity, Back and per-RUN preferences |
| Pages | `RunViews.tsx`, `RecordsView.tsx`, `Explore.tsx`; `RecordDetail.tsx`, `MemoryView.tsx` and `SecondaryViews.tsx` reading/support pages |
| Themes | DaisyUI semantic tokens mapped to existing TAPL/VS Code colors, with retained manual light/dark selection |
| Hosts | Browser HTTP and VS Code stdio adapters share exact RUN and record-list contracts |

The [Viewer guide](../guides/viewer.md) is the behavior reference; gallery fixtures are not runtime data.

Current RUN shows expanded PLAN cards first, followed by In Progress TASK cards. PLAN previews objective, approach and validation; TASK previews goal, action, verification and compact recorded execution facts. Both use horizontal rows with fading edges, independent scroll positions and matching single-card/responsive sizing. Missing fields are omitted and long previews are limited; full content opens in Explore. All task states remain available in TASK status.

Shipping details follow the prototype hero, reading column, property rail and real related-record rows. Meaningful typed fields are promoted into the body; additional values form a vertical object/array tree. Memory uses note cards and source previews. Workspace selection is a modal, and diagnostics/errors/loading use the same visual system. Icon tooltips and status tokens are shared across pages. Synthetic prototype checks, relationships and metadata are never copied as runtime facts.

PLAN detail reads its typed sections without a separate Content section. Original PLAN body text remains inside collapsed additional fields, including older records with differently formatted generated Markdown.

## Ten directions

| Concept | Main information structure | Extension adaptation | Fit and limitation |
| --- | --- | --- | --- |
| **01 Signal Desk** | Task list alongside selected-task detail | Compact list and detail dialog | **Basis of the integrated TASK status view.** Balances work and evidence. |
| **02 Flow Board** | Pending, running, blocked and completed lanes | Status filter and vertical lanes | **Basis for task flow below Current RUN in the integrated concept.** More tasks make the page longer. |
| **03 Focus Now** | Current task, purpose, verification and next queue | Prioritize the current task | An alternative focused on the current task. Needs a separate comparison view. |
| 04 Evidence Stream | Chronological events and source records | Vertical timeline | Resuming and retrospectives; chronology is not dependency order. |
| 05 Record Library | Search results alongside source content | Results followed by content | Records and archives; less suitable for live execution. |
| 06 Memory Garden | Lessons, recall cues and sources | Single-column memory cards | Dedicated memory screen; progressively disclose long content. |
| 07 Run Atlas | RUN cards with owners and sources | Vertical RUN list | Multiple sessions and peer history; excessive for a single RUN. |
| 08 Spec Explorer | TASK and FINDING navigation under PLAN | Navigation followed by content | Long plans and verification records; collapse deep hierarchies. |
| 09 Dependency Lens | Prerequisite and downstream TASK connections | Read conditions from top to bottom | Blocker analysis; graph layout requires separate implementation. |
| 10 Quiet Outline | Short outline, task list and collapsed records | Single-column progressive disclosure | Reading and keyboard use; needs an auxiliary comparison view. |

The integrated concept **combines the 02-based Current RUN and 01-based TASK status as Workspace pages**, uses 05 for search, 06 for memory and 08's information structure for record exploration. It does not add all ten as product view options. The dependency view from 09 remains an optional follow-up.

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

The product pins DaisyUI **5.7.50**, Tailwind CSS and `@tailwindcss/vite` **4.3.5** in `pnpm-lock.yaml`. React **18.3.1**, Vite **5.4.20** and the VS Code **1.90** minimum remain unchanged. `styles.css` uses `@import "tailwindcss"` and `@plugin "daisyui"`; legacy JavaScript Tailwind/PostCSS configs are removed. Build through Vite and synchronize browser assets with `compile`.

The semantic color adapter preserves VS Code variables, browser defaults and manual themes. Explicit join focus/hover fallbacks cover selectors omitted by the upstream CSS optimizer. See the [DaisyUI upgrade guide](https://daisyui.com/docs/upgrade/) and [Tailwind upgrade guide](https://tailwindcss.com/docs/upgrade-guide).

### 2. Separate shared UI responsibilities

Workbench modules own navigation and page composition. Existing record content, custom fields, execution details, memory views, workspace choice, diagnostics and the exact-ID discard dialog remain shared. Host adapters preserve origin/CSP, source identity, read-only access and stale-result protection. Missing run context from older hosts does not fabricate active records; upgrade the MCP server for the new record library.

### 3. Apply the selected UX

The product uses fixed RUN tabs and sidebar, compact present metadata, horizontal PLAN/Flow sections, a full TASK list and one hover/click Explore panel. TASK selection opens a detailed page. Record search defaults to all records with collapsed groups. An archived source gets one temporary tab; Back restores source context, filter, scroll and focus. See [Viewer navigation](../guides/viewer.md#navigate-the-viewer).

### 4. Verify before adoption

Use the [contributing checks](contributing.md) for shared webview TypeScript, host contracts, real Chrome behavior, Python read-only/source tests and packaged assets. Run real VS Code, high-contrast and screen-reader checks when those environments are available; browser and mocked host checks alone do not establish them. Gallery validation below applies only to the synthetic examples.

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
