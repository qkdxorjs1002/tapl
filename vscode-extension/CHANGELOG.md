# Changelog

All notable changes to TAPL Workflow Viewer are documented in this file.

## 2.23.0 - 2026-11-17

- Close temporary read-only RUN tabs with the X button or Delete key and return to the previous view without changing source history.
- Retain up to three complete automatic memory hints under one final 3,600-byte budget, preserving exact source pointers and duplicate-free reference tracking.
- Reuse existing cue labels before storing memories and register new concepts only when storage succeeds.
- Let agents merge equivalent cue labels, retain former labels as aliases, and deduplicate catalog links without rewriting existing memories or search indexes.
- Preserve successful capture retries across later cue merges and retain schema 14 read-only compatibility when upgrading to schema 15.
- Keep the original query tokenization and ranking without domain-specific synonym, particle, or summary-keyword heuristics.

## 2.22.2 - 2026-11-16

- Keep light/dark appearance changes inside TAPL; the Viewer no longer changes VS Code's theme or settings.
- Derive the local appearance from live VS Code colors while preserving native colors in matching mode, primary-button pairs, high-contrast boundaries and the saved TAPL choice.

## 2.22.1 - 2026-11-16

- Keep VS Code's native palette through theme changes; the Viewer theme button now toggles VS Code's own preferred light/dark themes and clears old web-palette overrides in the extension.
- Show the Viewer build version at the bottom center on every page, linking directly to its GitHub release.
- Highlight newer stable releases with a subtle ambient glow and a direct release link; respect reduced motion and cache public update checks.
- Connect explicitly used memories and history from earlier RUNs of the same conversation to the current RUN after checking recorded original-read evidence.
- Reuse existing source-qualified cards and connections, preserve the first usage reason, and show the Used state without duplicate nodes or edges.

## 2.21.4 - 2026-11-16

- Fix the visible automatic-following tooltip to show the current action on hover and keyboard focus in Korean and English.
- Preserve the toggle's accessible name and pressed state while showing the requested action text.

## 2.21.3 - 2026-11-16

- Follow Draft and Finalized PLANs before any TASK exists, while prioritizing executing work and keeping the RUN visible.
- Keep visible mindmaps rendering and following updates without window focus; pause hidden or offscreen maps and catch up automatically when shown again.
- Refresh visible VS Code Viewer panels even when another window has focus, while coalescing updates for hidden panels.
- Use concise automatic-following tooltips in Korean and English.
- Keep RUN titles and identifiers on separate lines at responsive screen sizes.

## 2.1.0 - 2026-08-18 (Pre-release)

- Open the Microsoft Marketplace pre-release channel for early updates.
- Use the same tested TAPL v2 viewer baseline as the initial stable release.

## 2.0.0 - 2026-08-18

- Publish TAPL Workflow Viewer to Microsoft Visual Studio Marketplace.
- Show active runs, plans, tasks, findings, approvals, archives, and search results.
- Connect through a persistent workspace-scoped `tapl-mcp` client.
- Refresh views when the workspace TAPL database changes.
- Provide responsive dashboard layouts and Korean/English localization.
