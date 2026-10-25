# Zotero Assistant — Agent Skill for Antigravity 2.0 (macOS)

[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-black?logo=apple)](https://www.apple.com/macos/)
[![Agent: Antigravity 2.0](https://img.shields.io/badge/Agent-Antigravity%202.0-4285F4?logo=google)](https://idx.dev/)
[![Zotero: v6 / v7](https://img.shields.io/badge/Zotero-6%20%7C%207-CC2936?logo=zotero)](https://www.zotero.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**`zotero-assistant`** is a lightweight, 100% device-independent agent skill developed for **macOS** and **Google Antigravity 2.0**. It enables seamless, simultaneous collaboration between researchers and their AI agent directly inside a local **Zotero** library (`~/Zotero`) — without ever locking or corrupting `zotero.sqlite`.

---

## ✨ Key Capabilities

1. **Conflict-Free Library & Metadata Search (`search`)**
   * Queries `~/Zotero/zotero.sqlite` in strictly read-only immutable mode (`?immutable=1`), preventing `SQLITE_BUSY` / `database is locked` errors while Zotero Desktop is open.
   * Filters by title, author, abstract, DOI, collection, or tag, and resolves local PDF paths inside `~/Zotero/storage/<KEY>/`.
2. **Live Annotation & Note Inspection (`annotations`)**
   * Reads native Zotero highlights, page numbers, hex colors, comments (`itemAnnotations`), standalone notes (`itemNotes`), and embedded external PDF annotations while automatically filtering out trashed items (`deletedItems`).
3. **Context-Aware PDF Reading (`read-pdf`)**
   * Extracts full text by page range (`all`, `1-3`, `1,4,6`) or locates specific terms/concepts with bounding box coordinates and surrounding context lines.
4. **Simultaneous Collaborative PDF Highlighting (`highlight`)**
   * Writes standard ISO 32000-1 highlight annotations and pop-up notes directly into the Zotero PDF using PyMuPDF (`pymupdf`) — leaving `zotero.sqlite` untouched.
   * Uses a distinct default color (**Blue `#2ea8e5`**) and author tag (**`AI-Agent`**) so AI suggestions are visually separated from user highlights.
   * Enforces automatic, conversation-scoped backups (`<appDataDir>/brain/<conversation-id>/backups/`) and atomic file replacement (`os.replace`) so `/private/tmp` and project repositories remain completely clean.

---

## 🚀 Installation (macOS & Antigravity 2.0)

### Prerequisites
* **macOS** (uses built-in `/usr/bin/python3` for zero-latency SQLite queries inside the Antigravity sandbox)
* **Zotero 6 or 7** with local data directory at `~/Zotero`
* **[`uv`](https://docs.astral.sh/uv/)** (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`) for isolated on-the-fly execution of `pymupdf` via PEP 723 script metadata

### Global Installation (Recommended — available across all workspaces)

Clone directly into your global Antigravity skills directory:

```bash
git clone https://github.com/JuliusD9500/zotero-assistant.git ~/.gemini/config/skills/zotero-assistant
```

### Project-Local Installation (Single workspace)

```bash
git clone https://github.com/JuliusD9500/zotero-assistant.git .agents/skills/zotero-assistant
```

---

## 🛠️ CLI Subcommands (`scripts/zotero_cli.py`)

| Subcommand | Execution Engine | Description |
| :--- | :--- | :--- |
| `search` | `/usr/bin/python3` (stdlib) | Search Zotero items by `--query`, `--collection`, `--tag`, and `--limit` (default: `all`). |
| `annotations` | `/usr/bin/python3` (stdlib) | Extract native Zotero DB highlights/notes and embedded PDF annotations for `--item-id` or `--attachment-id`. |
| `read-pdf` | `uv run --no-project` | Extract page text (`--pages`) or search terms with bounding boxes (`--search`). |
| `highlight` | `uv run --no-project` | Add PDF highlights + pop-up comments (`--highlights-json` or `--term` / `--comment`) with automatic backup in `--backup-dir`. |

---

## 🤝 Collaborative Zotero 7 Workflow

When the agent highlights terms in a PDF you currently have open in Zotero 7:

1. **Reload the PDF Tab:** Briefly close and reopen the PDF tab in Zotero so Zotero reloads the updated file from disk.
2. **Unlock External Highlights for Full Editing (Removing the `🔒` Icon):**
   * Because the agent writes standard PDF annotations into the file rather than modifying `zotero.sqlite`, Zotero displays them with a read-only lock icon (`🔒`).
   * To convert them into native, fully editable Zotero annotations:
     1. Keep the PDF open in the Zotero PDF Reader.
     2. In the top **macOS menu bar**, click **File** (German: **Ablage**).
     3. Select **“Import Annotations…”** (German: **„Anmerkungen importieren…“**) and confirm.

---

## 📂 Repository Structure

```text
zotero-assistant/
├── README.md                 # Documentation & installation guide
├── LICENSE                   # MIT License
├── SKILL.md                  # Antigravity 2.0 agent instructions & guardrails
└── scripts/
    └── zotero_cli.py         # PEP 723 CLI utility (sqlite3 + pymupdf)
```

---

## 📄 License

Released under the [MIT License](LICENSE).
