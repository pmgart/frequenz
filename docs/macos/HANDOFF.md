# FREQUENZ on macOS: handoff

- Branch: `macos-app`, created from `main` (v0.2.1). `main` is not changed.
- Approved plan: [PLAN.md](PLAN.md) (rev 1, approved 2026-11-07).
- Last updated: 2026-11-09.

## Status
- Done on this branch: one codebase with macOS checks (data folder, OpenGL 3.3 request, display check through GTK, Command and Control for search and quit, ⌘ labels), a first-launch copy of a bundled globe map (only when `FREQUENZ_BUNDLE_RESOURCES` is set), a manual OpenGL probe, and a setup script.
- Verified on Linux: the test suite passes and the window starts. Linux behaviour is unchanged.
- Not verified on macOS yet: everything listed above. That is Phase 0.
- Not started: the app bundle and `.dmg` (Phase 2), the real-hardware checks beyond Phase 0 (Phase 3), a release (Phase 4).

## Set up on the MacBook
You need Homebrew (https://brew.sh) and the Xcode Command Line Tools (`xcode-select --install`).

```
brew install gh
gh auth login
gh repo clone pmgart/frequenz ~/Developer/frequenz
cd ~/Developer/frequenz
git switch macos-app
scripts/macos-setup.sh
```

`gh auth login` opens the browser. Log in there; no token goes into Terminal.

Then check the OpenGL path and start the app:

```
.venv/bin/python tests/globe_gl_probe.py 12
.venv/bin/frequenz
```

If a step in the script fails, run the same commands by hand, in the order the script lists them.

## What to report back
- `sw_vers -productVersion` and `uname -m`
- the full output of `.venv/bin/frequenz doctor`
- the last 10 lines of the probe output
- what the window does (a screenshot or a description)
- the exact text of any error

## Known gaps
- Inter, the UI font, is not installed by the script. Without it the UI falls back to the system font. Install Inter from https://rsms.me/inter/ for the intended look.
- The OpenGL 3.3 path has never run on real hardware. The probe answers that.
- The app runs from source only: no app bundle and no signature.
- Quit is ⌘Q; Control-Q works too. Search is `/`, ⌘F or Control-F.

## Tests
```
.venv/bin/python -m pytest -q
.venv/bin/python -m pyflakes frequenzradio tests
```
