THIS IS FOR PERSONAL USE BUT ITS PUBLIC BECAUSE IDC

# BetterMechanic

A fast photo browser for culling, tagging and ingesting — in the spirit of Photo Mechanic, with
**tag presets**: every number key tags a player (or anyone) from the active preset, and you switch
presets per sport or team.

```
 (Hockey)        (Soccer)
 1: Gustav       1: Stan
 2: John         2: Joe
 3: Mark         3: Shawn
 …               …
 ⇧1 … ⇧0  = players 11–20
```

## Features

- **Fast previews.** RAW files are never demosaiced: the JPEG previews cameras embed are read directly
  (Canon CR2/CR3, Nikon NEF, Sony ARW, Fuji RAF, Panasonic RW2, DNG, Olympus ORF, Pentax PEF and other
  TIFF-style RAWs). JPEG files use the EXIF thumbnail and the MPF preview first. Thumbnails load
  for what's on screen first, then the rest in the background, on several threads.
- **Tag presets.** Up to 20 names per preset: keys **1–0** and **Shift + 1–0**. Press a key again to
  remove that name. Make as many presets as you like (Hockey, Soccer, Team A…) and switch with **P / Shift+P**.
  Each preset can add extra keywords and can rewrite the caption from a template whenever players change
  (e.g. `{people} of HIFK in action against Tappara, {longdate}.`). Paste a roster (one name per line) to fill
  a preset, and import/export presets as JSON.
- **Player picker and rosters.** Each preset has a roster with no size limit: names, jersey numbers and photos
  from an image link or a file on your computer. Press **F** and the picker opens: type part of a name or a number,
  move with the arrows or the mouse wheel, and press **Enter** to tag (**Shift+Enter** tags and keeps it open for the next
  player, **Tab** searches every preset). Typing a new name offers to add it to the roster. Paste a whole roster from a
  spreadsheet or team page (`9, Gustav Forsling, https://…/9.jpg`); players without a photo get coloured initials.
- **Edit with Lightroom presets.** Import presets in bulk: `.xmp` and older `.lrtemplate` files, whole folders, or the `.zip`
  packs they're sold in. They're grouped by the preset's group or folder, searchable, and apply with an **Amount** slider.
  Edit in the app too (press **D**): white balance, exposure, contrast, highlights, shadows, whites, blacks, texture,
  clarity, dehaze, vibrance, saturation, a colour mixer (HSL) and black & white, vignette, grain and sharpening, with
  before/after (**Y**) and copy / paste / reset (**Ctrl+Shift+C / V / R**). Edits are saved as Lightroom / Camera Raw
  settings in the XMP, so Lightroom and Photoshop apply them to the RAW; BetterMechanic shows a close approximation
  based on the camera's embedded JPEG, and bakes it into JPEG exports.
- **Metadata presets.** Templates for caption, headline, event, credit, copyright, city, keywords and the rest of
  the IPTC fields. Variables such as `{people}`, `{event}`, `{longdate}`, `{camera}` and `{seq}` are filled in per photo.
  Apply them with one click, or automatically during ingest.
- **Culling.** Tag (T), reject (X), stars (Alt+1–5), color labels (Alt+6–9), filters (tagged, rejected,
  rated, has players …), and search by file name, player, keyword or caption.
- **Cull straight from the card.** Open a memory card (any folder with a DCIM folder) and it opens read-only with all its
  subfolders. Tag, reject, rate and tag players; BetterMechanic remembers your choices (nothing is written to the card,
  and they're still there if you close the app), then **Ingest Tagged** or **Ingest All Except Rejected**.
- **Ingest with culling.** Open a memory card read-only and cull and tag it *before* anything is copied.
  Then copy only what you keep (all except rejected, tagged only, rated, …) to a destination plus an optional
  backup drive, with subfolder and rename templates (`{yyyy}-{mm}-{dd}`, `{date}_{seq:4}`). Tags, players and
  the metadata preset are written into the copies. An ingest history skips photos you already ingested.
- **Copy & export.** Same engine: copy originals, or export resized JPEGs for sending.
- **Large preview.** Fit-to-screen preview with neighbour prefetch, click or **Z** for 100% and drag to pan,
  plus a filmstrip.
- **Standard metadata.** Players go to IPTC *Person shown* (and keywords, optional). JPEGs get XMP and
  IPTC-IIM written into the file header (pixels are never re-encoded). RAW files get an `.xmp` sidecar, merged
  with whatever Lightroom/Capture One already wrote there. Ratings, labels and the tag flag use the same
  fields as Lightroom and Photo Mechanic.
- RAW + JPEG pairs are shown as one photo; edits go to both.
- **Native-feeling interface** modelled on Apple's Human Interface Guidelines: system font and colors,
  a quiet icon toolbar, a source-list sidebar, an inspector of grouped sections, and light/dark appearance
  that follows the system (or set it in Settings). The large preview always stays dark.

## Download (Windows)

Grab the latest release from the [Releases page](https://github.com/Rtx-9/bettermechanic/releases/latest):

- **`BetterMechanic.exe`**: a single file, no install. It unpacks itself on each start, so it takes a few seconds to open.
- **`BetterMechanic-<version>-win64.zip`**: a portable folder that starts faster. Unzip it anywhere and run `BetterMechanic.exe`.

The executables are not code-signed, so Windows SmartScreen may say *"Windows protected your PC"*:
click **More info → Run anyway**.

## Run from source

You need Python 3.10 or newer.

**Windows:** double-click `run.bat`. The first run creates a virtual environment and installs the
dependencies (PySide6 and Pillow).

**Any OS:**

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip ...
.venv/bin/python -m bettermechanic [folder]
```

Settings and presets are stored in `%APPDATA%\BetterMechanic` (Windows),
`~/Library/Application Support/BetterMechanic` (macOS) or `~/.config/BetterMechanic` (Linux).

## Keyboard

| Keys | Action |
|---|---|
| `1` … `0` | Toggle player 1–10 of the active tag preset |
| `Shift` + `1` … `0` | Toggle player 11–20 |
| `P` / `Shift+P` | Next / previous tag preset |
| `F` (or `/`) | Player picker: type a name or number, `Enter` to tag |
| `D` | Edit: presets and adjustments |
| `Y` | Before / after |
| `Ctrl+Shift+C` / `V` / `R` | Copy / paste / reset edit settings |
| `Backspace` | Remove all players from the selection |
| `T` | Tag (pick) |
| `X` | Reject |
| `Alt` + `1`…`5` / `Alt+0` | Star rating / clear |
| `Alt` + `6` `7` `8` `9` | Red / yellow / green / blue label |
| `Enter` / `Space` | Large preview ↔ contact sheet |
| `Z` or click | 100% zoom (drag to pan) |
| Arrows, `Shift`+arrows | Move / extend selection |
| `Ctrl+O` / `Ctrl+I` / `Ctrl+E` | Open folder / ingest from card / copy & export |
| `Ctrl+S` | Save metadata now (it also saves automatically) |
| `Ctrl+A` / `Ctrl+D` / `Ctrl+F` | Select all / none / search |
| `F1` | Help |

Number keys are read by their physical position, so Shift + number works on any keyboard layout.
In the contact sheet, keys act on all selected photos; in the large preview, on the photo shown.

## Building the .exe

```bash
pip install pyinstaller
python packaging/make_icon.py      # only if you changed the icon
python packaging/build.py          # writes dist/BetterMechanic.exe and dist/BetterMechanic-<version>-win64.zip
```

## Tests

```bash
python -m unittest discover tests
python tests/samples.py demo_card     # writes a small fake memory card to try the app with
```

The tests build synthetic JPEG/NEF/CR3/ORF files and check preview extraction, orientation,
XMP/IPTC round-trips, sidecar merging and the ingest copy.

## License

BetterMechanic is free software, released under the [GNU General Public License v3.0](LICENSE)
(or, at your option, any later version).
