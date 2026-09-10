# README artwork

The README uses an original mint-and-petrol ribbon mark and a dark conversation
panel. The connected ribbon represents workflow context carried between sessions.

## Logo

`tapl-logo.png` was generated with the built-in `image_gen` tool. The exact prompt
is saved in [logo-prompt.txt](logo-prompt.txt). It has a transparent background and
is referenced directly, without external image hosting.

## Workflow demo

`workflow-en.gif` and `workflow-ko.gif` show **illustrative public progress
messages**, not a captured Codex session or private model reasoning. The example
investigates a permission-check issue, so `Investigation · Strict · Planned` fits
the scenario. Other requests can use different classifications and fewer stages.
The investigation records evidence; it does not pretend to implement a fix.

Each animation has a matching PNG for readers who prefer a still image, and an
editable HTML composition. The same progress is described in README text.

Regenerate both languages with Python 3, Chrome/Chromium, FFmpeg, and a system font
that covers Korean and emoji:

```sh
python3 assets/readme/render-demo.py
```

The renderer uses a temporary browser profile. Set `CHROME` to an alternative
Chrome/Chromium executable path when required. It updates only the demo files;
it does not modify the logo. The discrete frame reveals avoid rapid motion and
leave the complete sequence visible for at least six seconds before repeating.

Rendered typography may vary with the installed system fonts. The committed GIF
and PNG assets preserve the reviewed appearance for GitHub readers.
