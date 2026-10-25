---
name: zotero-assistant
description: >-
  Read, search, and collaboratively annotate papers and PDFs in the local Zotero
  library (~/Zotero) on macOS. Use when the user asks about papers, highlights,
  notes, tags, or collections in Zotero, wants context-aware answers on a Zotero
  PDF, or asks the agent to add, modify, or manage PDF highlights and comments
  alongside their own work.
---

# Zotero Assistant (macOS & Antigravity 2.0)

## Overview

Enables seamless, simultaneous collaboration between the user and the AI agent inside the local **Zotero** library (`~/Zotero`) on **macOS** within **Google Antigravity 2.0**:

1. **Library & Metadata Discovery:** Search items across `~/Zotero/zotero.sqlite` by title, author, DOI, collection, or tag, and resolve attached PDF paths in `~/Zotero/storage/<KEY>/`.
2. **Reading User Highlights & Notes:** Extract both native Zotero annotations (`itemAnnotations`, `itemNotes`) and embedded PDF annotations to understand what the user has highlighted or commented on.
3. **Context-Aware PDF Reading:** Read full pages or search specific terms/concepts with surrounding context and bounding boxes directly from the Zotero PDF.
4. **Collaborative PDF Highlighting:** Write standard ISO PDF highlight annotations and pop-up comments (using a distinct AI color `#2ea8e5` and author label `AI-Agent`) directly into the Zotero PDF file without ever modifying `zotero.sqlite`.

---

## Dependencies & Execution Mode (CRITICAL FOR SANDBOX)

> [!IMPORTANT]
> **Preventing `uv run` Sandbox DNS / Permission Errors in Antigravity 2.0:**
> Antigravity's Standard Sandbox (`BypassSandbox: false`) disables DNS/network access and blocks spawning cached virtualenv binaries inside `~/.cache/uv`. Running `uv run` inside the Standard Sandbox will therefore fail with `Failed to fetch: https://pypi.org/simple/pymupdf/ (dns error)` or `Operation not permitted`.
>
> Follow this two-tier execution rule:
> 1. **`search` & `annotations` (SQLite-only, zero external dependencies):**
>    * Execute via **`/usr/bin/python3`** (universal macOS system Python with built-in `sqlite3`).
>    * Works **inside the Standard Sandbox (`BypassSandbox: false`)** whenever `~/Zotero` is readable in the workspace; otherwise retry with `BypassSandbox: true`.
> 2. **`read-pdf` & `highlight` (requires `pymupdf` via `uv run --no-project`):**
>    * **MUST be executed with `BypassSandbox: true` from the very first call** (per the `"unless mentioned otherwise"` exception in `<terminal_sandbox>` Rule 1). Do **not** run `uv run` with `BypassSandbox: false` first.

* **`uv`** (Prerequisite skill: `uv`): Used for `read-pdf` and `highlight` via `uv run --no-project`. The script `scripts/zotero_cli.py` declares `pymupdf` via inline PEP 723 metadata (`# /// script`), so `uv` automatically provisions `pymupdf` in `~/.cache/uv` on any Mac without touching project environments.

---

## Strict Guardrails

1. **Never Write to `zotero.sqlite`:**
   * All SQLite connections **MUST** use `file:/path/to/zotero.sqlite?immutable=1`.
   * This prevents `database is locked` errors while Zotero Desktop is open and guarantees 100% database integrity.
2. **Conversation-Scoped Backups Only (`<appDataDir>/brain/<conversation-id>/backups/`):**
   * Before modifying any PDF in `~/Zotero/storage/`, an untouched backup of the original PDF **MUST** be saved in `<appDataDir>/brain/<conversation-id>/backups/`.
   * **Never** place PDF backups inside the user's project repository, and **never** leave temporary files in `/tmp` or `/private/tmp`.
3. **Visual Separation (`AI-Agent` & `#2ea8e5`):**
   * Default to **Blue (`#2ea8e5`)** and author tag **`AI-Agent`** when creating highlights so the user can immediately distinguish AI suggestions from their own highlights (typically yellow `#ffd400`).
4. **Default to Returning All Results (`--limit all`):**
   * By default, `--limit` is optional and set to `all` so no items, annotations, or pages are silently truncated. Pass a number (e.g., `--limit 10`) only when a subset is explicitly desired.

---

## Quick Start

```bash
# 1. Search Zotero library (Standard Sandbox: /usr/bin/python3)
/usr/bin/python3 ~/.gemini/config/skills/zotero-assistant/scripts/zotero_cli.py search \
  --query "attention" \
  --output <appDataDir>/brain/<conversation-id>/scratch/zotero_search.json

# 2. Read user highlights and notes (Standard Sandbox: /usr/bin/python3)
/usr/bin/python3 ~/.gemini/config/skills/zotero-assistant/scripts/zotero_cli.py annotations \
  --attachment-id 42 \
  --output <appDataDir>/brain/<conversation-id>/scratch/zotero_annotations.json
```

---

## Utility Scripts

Script path: `~/.gemini/config/skills/zotero-assistant/scripts/zotero_cli.py` (or `.agents/skills/zotero-assistant/scripts/zotero_cli.py` if installed locally).

### 1. `search` — Search Items, Collections, Tags & PDF Paths

Run with `/usr/bin/python3`:

```bash
/usr/bin/python3 ~/.gemini/config/skills/zotero-assistant/scripts/zotero_cli.py search \
  --query "transformer" \
  --collection "Reading List" \
  --limit all \
  --output <appDataDir>/brain/<conversation-id>/scratch/search_results.json
```

* `--query` *(optional)*: Case-insensitive substring match on title, creators, abstract, DOI, or filename.
* `--collection` *(optional)*: Filter by Zotero collection name.
* `--tag` *(optional)*: Filter by Zotero tag name.
* `--limit` *(optional, default: `all`)*: Use `all` (or omit) to return all matching items, or pass an integer.
* `--output` *(required)*: Path to output JSON file.

### 2. `annotations` — Read Native Zotero & Embedded PDF Annotations

Run with `/usr/bin/python3` for native Zotero DB annotations (or with `uv run --no-project` and `BypassSandbox: true` to also inspect unimported external PDF annotations):

```bash
/usr/bin/python3 ~/.gemini/config/skills/zotero-assistant/scripts/zotero_cli.py annotations \
  --item-id 41 \
  --limit all \
  --output <appDataDir>/brain/<conversation-id>/scratch/item_annotations.json
```

* `--item-id` or `--attachment-id`: Either the parent Zotero `itemID` or the PDF `attachmentID`.
* `--limit` *(optional, default: `all`)*: Returns all annotations by default.
* Returns:
  * `zoteroDbAnnotations`: Native Zotero highlights, page numbers (`pageLabel`), hex colors, highlighted `text`, and user `comment` notes (excluding trashed items in `deletedItems`).
  * `pdfEmbeddedAnnotations`: External annotations embedded in the PDF file stream (populated when run via `uv run --no-project`).
  * `itemNotes`: Standalone Zotero notes attached to the item.

### 3. `read-pdf` — Extract Text or Search Terms with Context

**Always call `run_command` with `BypassSandbox: true`:**

```bash
# Search for specific terms with bounding boxes and surrounding context lines
uv run --no-project ~/.gemini/config/skills/zotero-assistant/scripts/zotero_cli.py read-pdf \
  --attachment-id 42 \
  --search "methodology" "hypothesis" \
  --pages all \
  --limit all \
  --output <appDataDir>/brain/<conversation-id>/scratch/pdf_matches.json

# Or extract full text of specific pages
uv run --no-project ~/.gemini/config/skills/zotero-assistant/scripts/zotero_cli.py read-pdf \
  --attachment-id 42 \
  --pages "1-3" \
  --output <appDataDir>/brain/<conversation-id>/scratch/pdf_pages.json
```

### 4. `highlight` — Add Collaborative PDF Highlights & Comments

**Always call `run_command` with `BypassSandbox: true`:**

```bash
uv run --no-project ~/.gemini/config/skills/zotero-assistant/scripts/zotero_cli.py highlight \
  --attachment-id 42 \
  --backup-dir <appDataDir>/brain/<conversation-id>/backups \
  --highlights-json '[
    {
      "term": "core theoretical contribution",
      "page": 1,
      "comment": "Central definition for the literature review.",
      "color": "#2ea8e5",
      "author": "AI-Agent"
    }
  ]' \
  --output <appDataDir>/brain/<conversation-id>/scratch/highlight_report.json
```

* Automatically copies the untouched original PDF to `<backup-dir>/<stem>_original_backup.pdf` (if not already backed up) and stages changes atomically inside `<backup-dir>` without touching `/private/tmp`.

---

## Collaborative Zotero 7 Workflow (User Guidance)

Whenever you add or update highlights in a Zotero PDF, inform the user of these two Zotero 7 behaviors:

1. **Refreshing an Open PDF Tab in Zotero:**
   * If the user already had the PDF tab open in Zotero while you added highlights, Zotero holds the previous file state in memory.
   * **Action:** Briefly close and reopen the PDF tab (or switch tabs) in Zotero to see the new highlights immediately.
2. **Unlocking External Highlights for Editing (Removing the Lock Icon 🔒):**
   * Because the agent writes standard PDF annotations into the file (rather than writing into `zotero.sqlite`), Zotero 7 displays them with a lock icon (`🔒`) as read-only external annotations.
   * **Action to make them natively editable in Zotero 7:**
     1. Keep the PDF tab open in the Zotero PDF Reader.
     2. In the top **macOS menu bar**, click **File** (German: **Ablage**).
     3. Select **„Import Annotations…“** (German: **„Anmerkungen importieren…“**) and confirm.
     * *(Alternatively: In the main Zotero library tab, expand the paper entry, right-click the PDF attachment $\rightarrow$ „Import Annotations…“ / „Anmerkungen importieren…“).*
     4. Zotero imports the highlights into `zotero.sqlite`, removes the lock icon `🔒`, and allows full editing of colors, comments, and text.

---

## Common Mistakes

* **Running `uv run` inside the Standard Sandbox (`BypassSandbox: false`):** Causes `Failed to fetch: https://pypi.org/simple/pymupdf/ (dns error)` because the sandbox disables DNS and blocks executing binaries from `~/.cache/uv`. Always set `BypassSandbox: true` when running `read-pdf` or `highlight`.
* **Opening `zotero.sqlite` without `?immutable=1`:** Causes `sqlite3.OperationalError: database is locked (5)` whenever Zotero Desktop is running. Always use `?immutable=1`.
* **Storing backups in the project repository or `/private/tmp`:** Backups belong strictly in `<appDataDir>/brain/<conversation-id>/backups/`.
