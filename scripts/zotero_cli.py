#!/usr/bin/env -S uv run --no-project
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "pymupdf",
# ]
# ///
"""Zotero Library & Collaborative PDF Annotation CLI.

100% device-independent CLI script for reading and collaboratively annotating
Zotero PDFs. Uses PEP 723 inline script metadata so `uv run --no-project`
automatically provisions `pymupdf` in an isolated cache on any machine.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sqlite3
import sys
from typing import Any

try:
  import pymupdf
except ImportError:
  pymupdf = None  # type: ignore


DEFAULT_AI_COLOR = "#2ea8e5"
DEFAULT_AI_AUTHOR = "AI-Agent"

ANNOTATION_TYPE_MAP = {
    1: "highlight",
    2: "note",
    3: "image",
    4: "ink",
    5: "underline",
}


def require_pymupdf() -> Any:
  """Ensures pymupdf is available for PDF operations."""
  if pymupdf is None:
    raise RuntimeError(
        "PyMuPDF (pymupdf) is required for PDF operations. Run this script via "
        "`uv run --no-project ~/.gemini/config/skills/zotero-assistant/scripts/zotero_cli.py ...` "
        "with `BypassSandbox: true`."
    )
  return pymupdf


def parse_limit(val: str | None) -> int | None:
  """Parses a --limit argument ('all', '0', None, or positive int)."""
  if val is None:
    return None
  s = str(val).strip().lower()
  if s in ("all", "0", "none", ""):
    return None
  try:
    n = int(s)
    return n if n > 0 else None
  except ValueError:
    raise argparse.ArgumentTypeError(
        f"Invalid limit '{val}'. Use a positive integer or 'all'."
    )


def hex_to_rgb_floats(hex_color: str) -> tuple[float, float, float]:
  """Converts a hex color string like '#2ea8e5' to RGB floats in [0.0, 1.0]."""
  h = hex_color.lstrip("#")
  if len(h) != 6:
    return (0.18, 0.66, 0.90)
  return (
      int(h[0:2], 16) / 255.0,
      int(h[2:4], 16) / 255.0,
      int(h[4:6], 16) / 255.0,
  )


def connect_zotero_db(zotero_dir: pathlib.Path) -> sqlite3.Connection:
  """Opens zotero.sqlite in strictly read-only immutable mode."""
  db_path = zotero_dir / "zotero.sqlite"
  if not db_path.exists():
    raise FileNotFoundError(f"Zotero database not found at: {db_path}")
  uri = f"file:{db_path.resolve()}?immutable=1"
  conn = sqlite3.connect(uri, uri=True)
  conn.row_factory = sqlite3.Row
  return conn


def resolve_attachment_pdf_path(
    zotero_dir: pathlib.Path, attachment_key: str, raw_path: str | None
) -> pathlib.Path | None:
  """Resolves Zotero's 'storage:filename.pdf' or absolute path to a Path."""
  if not raw_path:
    return None
  if raw_path.startswith("storage:"):
    filename = raw_path[len("storage:") :]
    return zotero_dir / "storage" / attachment_key / filename
  p = pathlib.Path(raw_path).expanduser()
  return p


def get_pdf_for_attachment(
    conn: sqlite3.Connection, zotero_dir: pathlib.Path, attachment_id: int
) -> tuple[int, int | None, pathlib.Path]:
  """Returns (attachmentID, parentItemID, pdf_path) for an attachment or parent item."""
  cur = conn.cursor()
  cur.execute(
      """
      SELECT ia.itemID AS attachmentID, ia.parentItemID, ia.path, i.key
      FROM itemAttachments ia
      JOIN items i ON i.itemID = ia.itemID
      WHERE ia.itemID = ?
        AND ia.itemID NOT IN (SELECT itemID FROM deletedItems)
      """,
      (attachment_id,),
  )
  row = cur.fetchone()
  if not row:
    cur.execute(
        """
        SELECT ia.itemID AS attachmentID, ia.parentItemID, ia.path, i.key
        FROM itemAttachments ia
        JOIN items i ON i.itemID = ia.itemID
        WHERE ia.parentItemID = ?
          AND ia.contentType = 'application/pdf'
          AND ia.itemID NOT IN (SELECT itemID FROM deletedItems)
        ORDER BY ia.itemID ASC
        LIMIT 1
        """,
        (attachment_id,),
    )
    row = cur.fetchone()

  if not row:
    raise ValueError(
        f"No active PDF attachment found for ID {attachment_id} in Zotero."
    )

  pdf_path = resolve_attachment_pdf_path(
      zotero_dir, row["key"], row["path"]
  )
  if not pdf_path or not pdf_path.exists():
    raise FileNotFoundError(
        f"Resolved PDF file does not exist on disk: {pdf_path}"
    )
  return row["attachmentID"], row["parentItemID"], pdf_path


def cmd_search(args: argparse.Namespace) -> dict[str, Any]:
  """Searches Zotero items by query, collection, or tag."""
  zotero_dir = pathlib.Path(args.zotero_dir).expanduser().resolve()
  conn = connect_zotero_db(zotero_dir)
  cur = conn.cursor()

  cur.execute(
      """
      SELECT i.itemID, i.key, i.dateAdded, i.dateModified
      FROM items i
      WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
        AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
        AND i.itemID NOT IN (SELECT itemID FROM itemNotes)
        AND i.itemID NOT IN (SELECT itemID FROM itemAnnotations)
      ORDER BY i.itemID ASC
      """
  )
  base_items = cur.fetchall()

  results = []
  query_lower = args.query.lower() if args.query else None
  coll_lower = args.collection.lower() if args.collection else None
  tag_lower = args.tag.lower() if args.tag else None

  for base in base_items:
    item_id = base["itemID"]

    cur.execute(
        """
        SELECT fc.fieldName, idv.value
        FROM itemData id
        JOIN fieldsCombined fc ON fc.fieldID = id.fieldID
        JOIN itemDataValues idv ON idv.valueID = id.valueID
        WHERE id.itemID = ?
        """,
        (item_id,),
    )
    fields = {r["fieldName"]: r["value"] for r in cur.fetchall()}

    cur.execute(
        """
        SELECT c.firstName, c.lastName
        FROM itemCreators ic
        JOIN creators c ON c.creatorID = ic.creatorID
        WHERE ic.itemID = ?
        ORDER BY ic.orderIndex ASC
        """,
        (item_id,),
    )
    creators = [
        f"{r['lastName']}, {r['firstName']}".strip(", ")
        for r in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT col.collectionName
        FROM collectionItems ci
        JOIN collections col ON col.collectionID = ci.collectionID
        WHERE ci.itemID = ?
        """,
        (item_id,),
    )
    collections = [r["collectionName"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT t.name
        FROM itemTags it
        JOIN tags t ON t.tagID = it.tagID
        WHERE it.itemID = ?
        """,
        (item_id,),
    )
    tags = [r["name"] for r in cur.fetchall()]

    cur.execute(
        """
        SELECT ia.itemID AS attachmentID, i.key AS attachmentKey,
               ia.contentType, ia.path
        FROM itemAttachments ia
        JOIN items i ON i.itemID = ia.itemID
        WHERE ia.parentItemID = ?
          AND ia.itemID NOT IN (SELECT itemID FROM deletedItems)
        """,
        (item_id,),
    )
    attachments = []
    for att in cur.fetchall():
      resolved = resolve_attachment_pdf_path(
          zotero_dir, att["attachmentKey"], att["path"]
      )
      cur.execute(
          """
          SELECT COUNT(*) AS cnt
          FROM itemAnnotations
          WHERE parentItemID = ?
            AND itemID NOT IN (SELECT itemID FROM deletedItems)
          """,
          (att["attachmentID"],),
      )
      annot_cnt = cur.fetchone()["cnt"]
      attachments.append({
          "attachmentID": att["attachmentID"],
          "attachmentKey": att["attachmentKey"],
          "contentType": att["contentType"],
          "pdfPath": str(resolved) if resolved else None,
          "existsOnDisk": bool(resolved and resolved.exists()),
          "dbAnnotationCount": annot_cnt,
      })

    if coll_lower and not any(coll_lower in c.lower() for c in collections):
      continue
    if tag_lower and not any(tag_lower in t.lower() for t in tags):
      continue
    if query_lower:
      searchable_blob = " ".join([
          str(item_id),
          base["key"],
          fields.get("title", ""),
          fields.get("shortTitle", ""),
          fields.get("abstractNote", ""),
          fields.get("publicationTitle", ""),
          fields.get("date", ""),
          fields.get("DOI", ""),
          " ".join(creators),
          " ".join(a["pdfPath"] or "" for a in attachments),
      ]).lower()
      if query_lower not in searchable_blob:
        continue

    results.append({
        "itemID": item_id,
        "itemKey": base["key"],
        "title": fields.get("title", ""),
        "creators": creators,
        "date": fields.get("date", ""),
        "publicationTitle": fields.get("publicationTitle", ""),
        "DOI": fields.get("DOI", ""),
        "abstractNote": fields.get("abstractNote", ""),
        "collections": collections,
        "tags": tags,
        "attachments": attachments,
    })

  conn.close()

  total_found = len(results)
  limit = parse_limit(args.limit)
  if limit is not None:
    results = results[:limit]

  return {
      "totalMatched": total_found,
      "returnedCount": len(results),
      "limit": args.limit,
      "items": results,
  }


def cmd_annotations(args: argparse.Namespace) -> dict[str, Any]:
  """Fetches both Zotero DB annotations and embedded PDF annotations."""
  if not args.item_id and not args.attachment_id:
    raise ValueError("Provide either --item-id or --attachment-id.")

  zotero_dir = pathlib.Path(args.zotero_dir).expanduser().resolve()
  conn = connect_zotero_db(zotero_dir)
  cur = conn.cursor()

  target_id = args.attachment_id or args.item_id
  att_id, parent_id, pdf_path = get_pdf_for_attachment(
      conn, zotero_dir, target_id
  )

  cur.execute(
      """
      SELECT itemID, parentItemID, type, authorName, text, comment,
             color, pageLabel, sortIndex, position, isExternal
      FROM itemAnnotations
      WHERE parentItemID = ?
        AND itemID NOT IN (SELECT itemID FROM deletedItems)
      ORDER BY CAST(pageLabel AS INTEGER) ASC, sortIndex ASC
      """,
      (att_id,),
  )
  db_annotations = []
  for r in cur.fetchall():
    db_annotations.append({
        "source": "zotero_db",
        "annotationID": r["itemID"],
        "attachmentID": r["parentItemID"],
        "type": ANNOTATION_TYPE_MAP.get(r["type"], f"type_{r['type']}"),
        "pageLabel": r["pageLabel"],
        "color": r["color"],
        "text": r["text"],
        "comment": r["comment"],
        "authorName": r["authorName"],
        "sortIndex": r["sortIndex"],
        "position": json.loads(r["position"]) if r["position"] else None,
    })

  notes_query_ids = [att_id] + ([parent_id] if parent_id else [])
  placeholders = ",".join("?" for _ in notes_query_ids)
  cur.execute(
      f"""
      SELECT itemID, parentItemID, title, note
      FROM itemNotes
      WHERE parentItemID IN ({placeholders})
        AND itemID NOT IN (SELECT itemID FROM deletedItems)
      """,
      notes_query_ids,
  )
  item_notes = [dict(r) for r in cur.fetchall()]
  conn.close()

  pdf_annotations = []
  if pymupdf is not None and pdf_path and pdf_path.exists():
    doc = pymupdf.open(str(pdf_path))
    for page_idx, page in enumerate(doc):
      for annot in page.annots():
        info = annot.info or {}
        stroke_color = (annot.colors or {}).get("stroke")
        hex_col = None
        if stroke_color and len(stroke_color) == 3:
          hex_col = "#{:02x}{:02x}{:02x}".format(
              int(round(stroke_color[0] * 255)),
              int(round(stroke_color[1] * 255)),
              int(round(stroke_color[2] * 255)),
          )
        pdf_annotations.append({
            "source": "pdf_embedded_locked",
            "pageNumber": page_idx + 1,
            "type": annot.type[1] if annot.type else "Unknown",
            "authorName": info.get("title", ""),
            "comment": info.get("content", ""),
            "color": hex_col,
            "rect": list(annot.rect),
        })
    doc.close()

  limit = parse_limit(args.limit)
  if limit is not None:
    db_annotations = db_annotations[:limit]
    pdf_annotations = pdf_annotations[:limit]

  return {
      "parentItemID": parent_id,
      "attachmentID": att_id,
      "pdfPath": str(pdf_path),
      "zoteroDbAnnotationsCount": len(db_annotations),
      "pdfEmbeddedAnnotationsCount": len(pdf_annotations),
      "itemNotesCount": len(item_notes),
      "zoteroDbAnnotations": db_annotations,
      "pdfEmbeddedAnnotations": pdf_annotations,
      "itemNotes": item_notes,
  }


def parse_page_spec(page_spec: str | None, total_pages: int) -> list[int]:
  """Parses a 1-based page specification like 'all', '1-3', or '1,4,6' into 0-based indices."""
  if not page_spec or page_spec.strip().lower() == "all":
    return list(range(total_pages))
  indices: set[int] = set()
  for part in page_spec.split(","):
    part = part.strip()
    if not part:
      continue
    if "-" in part:
      start_s, end_s = part.split("-", 1)
      start_p = max(1, int(start_s))
      end_p = min(total_pages, int(end_s))
      for p in range(start_p, end_p + 1):
        indices.add(p - 1)
    else:
      p = int(part)
      if 1 <= p <= total_pages:
        indices.add(p - 1)
  return sorted(indices)


def cmd_read_pdf(args: argparse.Namespace) -> dict[str, Any]:
  """Extracts full text or searches for terms with context across PDF pages."""
  require_pymupdf()
  zotero_dir = pathlib.Path(args.zotero_dir).expanduser().resolve()
  if args.pdf_path:
    pdf_path = pathlib.Path(args.pdf_path).expanduser().resolve()
    att_id = None
  elif args.attachment_id:
    conn = connect_zotero_db(zotero_dir)
    att_id, _, pdf_path = get_pdf_for_attachment(
        conn, zotero_dir, args.attachment_id
    )
    conn.close()
  else:
    raise ValueError("Provide either --attachment-id or --pdf-path.")

  doc = pymupdf.open(str(pdf_path))
  total_pages = len(doc)
  page_indices = parse_page_spec(args.pages, total_pages)
  limit = parse_limit(args.limit)

  if args.search:
    matches = []
    for term in args.search:
      term_lower = term.lower()
      for p_idx in page_indices:
        page = doc[p_idx]
        rects = page.search_for(term)
        if not rects:
          continue
        lines = page.get_text().split("\n")
        contexts = []
        for idx, line in enumerate(lines):
          if term_lower in line.lower():
            start_l = max(0, idx - 2)
            end_l = min(len(lines), idx + 3)
            contexts.append("\n".join(lines[start_l:end_l]))
        matches.append({
            "term": term,
            "pageNumber": p_idx + 1,
            "matchCountOnPage": len(rects),
            "rects": [list(r) for r in rects],
            "contexts": contexts,
        })
    doc.close()
    total_matches = len(matches)
    if limit is not None:
      matches = matches[:limit]
    return {
        "pdfPath": str(pdf_path),
        "attachmentID": att_id,
        "totalPagesInPdf": total_pages,
        "totalMatches": total_matches,
        "returnedMatches": len(matches),
        "matches": matches,
    }

  pages_data = []
  for p_idx in page_indices:
    page = doc[p_idx]
    pages_data.append({
        "pageNumber": p_idx + 1,
        "text": page.get_text(),
    })
  doc.close()

  if limit is not None:
    pages_data = pages_data[:limit]

  return {
      "pdfPath": str(pdf_path),
      "attachmentID": att_id,
      "totalPagesInPdf": total_pages,
      "returnedPagesCount": len(pages_data),
      "pages": pages_data,
  }


def search_page_occurrences(page: Any, term: str) -> list[list[Any]]:
  """Searches a PDF page for term and groups word/line boxes into clean occurrences.

  Merges word-level rectangles on the same horizontal line (caused by justified
  PDF text) into a single continuous line rectangle, and groups consecutive
  wrapped lines of a multi-line phrase into a single occurrence list so that
  `page.add_highlight_annot(occ_rects)` creates one unified highlight per match.
  """
  flags = getattr(pymupdf, "TEXT_DEHYPHENATE", 0)
  raw_rects = page.search_for(term, flags=flags)
  if not raw_rects:
    raw_rects = page.search_for(term)
  if not raw_rects:
    alt_term = (
        term.replace("’", "'") if "’" in term else term.replace("'", "’")
    )
    if alt_term != term:
      raw_rects = page.search_for(alt_term, flags=flags) or page.search_for(
          alt_term
      )
  if not raw_rects:
    return []

  target_char_len = len("".join(term.split()))
  occurrences: list[list[Any]] = []
  first_rect = pymupdf.Rect(raw_rects[0])
  current_occ: list[Any] = [first_rect]
  current_chars = len("".join(page.get_text("text", clip=first_rect).split()))

  for r in raw_rects[1:]:
    r = pymupdf.Rect(r)
    r_chars = len("".join(page.get_text("text", clip=r).split()))
    last = current_occ[-1]
    line_height = max(last.height, r.height, 10.0)

    if current_chars < target_char_len * 0.95:
      # Same line -> merge into single continuous line rect
      if (
          abs(r.y0 - last.y0) <= max(3.0, line_height * 0.35)
          and abs(r.y1 - last.y1) <= max(3.0, line_height * 0.35)
          and -2.0 <= (r.x0 - last.x1) <= max(25.0, line_height * 2.5)
      ):
        current_occ[-1] = pymupdf.Rect(
            min(last.x0, r.x0),
            min(last.y0, r.y0),
            max(last.x1, r.x1),
            max(last.y1, r.y1),
        )
        current_chars += r_chars
        continue
      # Next line -> append as next line of the same occurrence
      if 0 < (r.y0 - last.y0) <= line_height * 3.0:
        current_occ.append(r)
        current_chars += r_chars
        continue

    occurrences.append(current_occ)
    current_occ = [r]
    current_chars = r_chars

  occurrences.append(current_occ)
  return occurrences


def validate_backup_dir(backup_dir: pathlib.Path) -> None:
  """Ensures --backup-dir is not in /tmp or /private/tmp."""
  resolved = str(backup_dir.resolve())
  if resolved.startswith("/tmp") or resolved.startswith("/private/tmp"):
    raise ValueError(
        f"Invalid --backup-dir '{resolved}': Backups must NEVER be placed in "
        "/tmp or /private/tmp. Use the Antigravity conversation folder "
        "(<appDataDir>/brain/<conversation-id>/backups/)."
    )


def cmd_highlight(args: argparse.Namespace) -> dict[str, Any]:
  """Adds PDF highlights with automatic conversation-scoped backup."""
  require_pymupdf()
  zotero_dir = pathlib.Path(args.zotero_dir).expanduser().resolve()
  if args.pdf_path:
    pdf_path = pathlib.Path(args.pdf_path).expanduser().resolve()
    att_id = None
  elif args.attachment_id:
    conn = connect_zotero_db(zotero_dir)
    att_id, _, pdf_path = get_pdf_for_attachment(
        conn, zotero_dir, args.attachment_id
    )
    conn.close()
  else:
    raise ValueError("Provide either --attachment-id or --pdf-path.")

  backup_dir = pathlib.Path(args.backup_dir).expanduser().resolve()
  validate_backup_dir(backup_dir)
  backup_dir.mkdir(parents=True, exist_ok=True)

  safe_stem = "".join(
      c if c.isalnum() or c in ("-", "_") else "_" for c in pdf_path.stem[:50]
  ).strip("_")
  backup_file = backup_dir / f"{safe_stem}_original_backup.pdf"
  if not backup_file.exists():
    shutil.copy2(pdf_path, backup_file)

  specs: list[dict[str, Any]] = []
  if args.highlights_json:
    hj_path = pathlib.Path(args.highlights_json).expanduser()
    if hj_path.exists() and hj_path.is_file():
      specs = json.loads(hj_path.read_text(encoding="utf-8"))
    else:
      specs = json.loads(args.highlights_json)
  elif args.term:
    specs = [{
        "term": args.term,
        "page": args.page,
        "comment": args.comment or "",
        "color": args.color or DEFAULT_AI_COLOR,
        "author": args.author or DEFAULT_AI_AUTHOR,
        "all_occurrences": args.all_occurrences,
    }]
  else:
    raise ValueError("Provide either --highlights-json or --term.")

  doc = pymupdf.open(str(pdf_path))
  applied = []
  not_found = []

  for spec in specs:
    term = spec["term"]
    target_page = spec.get("page")
    comment = spec.get("comment", "")
    color_hex = spec.get("color", DEFAULT_AI_COLOR)
    author = spec.get("author", DEFAULT_AI_AUTHOR)
    all_occ = bool(spec.get("all_occurrences", False))
    rgb = hex_to_rgb_floats(color_hex)

    page_indices = (
        [int(target_page) - 1]
        if target_page is not None
        else list(range(len(doc)))
    )

    found_any = False
    for p_idx in page_indices:
      if not (0 <= p_idx < len(doc)):
        continue
      page = doc[p_idx]
      occurrences = search_page_occurrences(page, term)
      if not occurrences:
        continue
      target_occs = occurrences if all_occ else [occurrences[0]]
      for occ_rects in target_occs:
        annot = page.add_highlight_annot(occ_rects)
        annot.set_colors(stroke=rgb)
        annot.set_info(title=author, content=comment)
        annot.update()
        applied.append({
            "term": term,
            "pageNumber": p_idx + 1,
            "color": color_hex,
            "author": author,
            "comment": comment,
            "rect": list(annot.rect),
            "lineRects": [list(r) for r in occ_rects],
        })
      found_any = True
      if not all_occ:
        break

    if not found_any:
      not_found.append({"term": term, "page": target_page})

  staging_file = backup_dir / f".staging_{safe_stem}.pdf"
  try:
    doc.save(str(staging_file))
    doc.close()
    os.replace(staging_file, pdf_path)
  finally:
    if staging_file.exists():
      staging_file.unlink()

  return {
      "pdfPath": str(pdf_path),
      "attachmentID": att_id,
      "backupPath": str(backup_file),
      "appliedCount": len(applied),
      "appliedHighlights": applied,
      "notFoundTerms": not_found,
      "zoteroUserInstructions": {
          "reloadTab": (
              "Falls das PDF in Zotero geöffnet ist: Tab kurz schließen und "
              "neu öffnen (oder Tab wechseln), damit Zotero die Datei neu lädt."
          ),
          "unlockForEditing": (
              "Um die Markierungen (Schloss-Symbol 🔒) in Zotero 7 frei "
              "bearbeitbar zu machen: Obere macOS-Menüleiste -> Ablage (File) "
              "-> 'Anmerkungen importieren…' (Import Annotations…)."
          ),
      },
  }


def write_output(data: dict[str, Any], output_file: str) -> None:
  """Writes JSON output to the specified file."""
  out_path = pathlib.Path(output_file).expanduser().resolve()
  out_path.parent.mkdir(parents=True, exist_ok=True)
  with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
  print(f"Success! Data written to: {out_path}")


def main() -> None:
  parser = argparse.ArgumentParser(
      description="Zotero Assistant CLI for reading and annotating Zotero PDFs."
  )
  subparsers = parser.add_subparsers(dest="command", required=True)

  p_search = subparsers.add_parser(
      "search", help="Search Zotero library items and resolve PDF paths."
  )
  p_search.add_argument("--query", help="Substring search (title/author/DOI).")
  p_search.add_argument("--collection", help="Filter by collection name.")
  p_search.add_argument("--tag", help="Filter by tag name.")
  p_search.add_argument(
      "--limit",
      default="all",
      help="Maximum items to return ('all' or positive integer, default: all).",
  )
  p_search.add_argument(
      "--zotero-dir", default="~/Zotero", help="Path to Zotero directory."
  )
  p_search.add_argument(
      "--output", required=True, help="Output JSON file path."
  )

  p_annot = subparsers.add_parser(
      "annotations",
      help="Fetch native Zotero DB annotations and embedded PDF annotations.",
  )
  p_annot.add_argument("--item-id", type=int, help="Parent Zotero itemID.")
  p_annot.add_argument(
      "--attachment-id", type=int, help="PDF attachment itemID."
  )
  p_annot.add_argument(
      "--limit",
      default="all",
      help="Maximum annotations to return ('all' or positive int, default: all).",
  )
  p_annot.add_argument(
      "--zotero-dir", default="~/Zotero", help="Path to Zotero directory."
  )
  p_annot.add_argument(
      "--output", required=True, help="Output JSON file path."
  )

  p_read = subparsers.add_parser(
      "read-pdf",
      help="Extract page text or search for terms with context in a Zotero PDF.",
  )
  p_read.add_argument(
      "--attachment-id", type=int, help="Zotero attachmentID or parent itemID."
  )
  p_read.add_argument("--pdf-path", help="Direct path to PDF file.")
  p_read.add_argument(
      "--pages",
      default="all",
      help="1-based page range, e.g. 'all', '1-3', or '1,4,6' (default: all).",
  )
  p_read.add_argument(
      "--search",
      nargs="*",
      help="Optional list of terms to search for with bounding boxes & context.",
  )
  p_read.add_argument(
      "--limit",
      default="all",
      help="Maximum pages or matches to return ('all' or int, default: all).",
  )
  p_read.add_argument(
      "--zotero-dir", default="~/Zotero", help="Path to Zotero directory."
  )
  p_read.add_argument(
      "--output", required=True, help="Output JSON file path."
  )

  p_high = subparsers.add_parser(
      "highlight",
      help="Add standard PDF highlights + comments with automatic backup.",
  )
  p_high.add_argument(
      "--attachment-id", type=int, help="Zotero attachmentID or parent itemID."
  )
  p_high.add_argument("--pdf-path", help="Direct path to PDF file.")
  p_high.add_argument(
      "--highlights-json",
      help="JSON string or file path with list of highlight specs.",
  )
  p_high.add_argument("--term", help="Single term to highlight.")
  p_high.add_argument(
      "--page", type=int, help="Optional 1-based page number for --term."
  )
  p_high.add_argument("--comment", help="Pop-up note/comment for --term.")
  p_high.add_argument(
      "--color",
      default=DEFAULT_AI_COLOR,
      help=f"Highlight hex color (default: {DEFAULT_AI_COLOR}).",
  )
  p_high.add_argument(
      "--author",
      default=DEFAULT_AI_AUTHOR,
      help=f"Annotation author label (default: {DEFAULT_AI_AUTHOR}).",
  )
  p_high.add_argument(
      "--all-occurrences",
      action="store_true",
      help="Highlight all occurrences of --term instead of only the first.",
  )
  p_high.add_argument(
      "--backup-dir",
      required=True,
      help="Must be <appDataDir>/brain/<conversation-id>/backups/.",
  )
  p_high.add_argument(
      "--zotero-dir", default="~/Zotero", help="Path to Zotero directory."
  )
  p_high.add_argument(
      "--output", required=True, help="Output JSON file path."
  )

  args = parser.parse_args()
  try:
    if args.command == "search":
      data = cmd_search(args)
    elif args.command == "annotations":
      data = cmd_annotations(args)
    elif args.command == "read-pdf":
      data = cmd_read_pdf(args)
    elif args.command == "highlight":
      data = cmd_highlight(args)
    else:
      raise ValueError(f"Unknown command: {args.command}")
    write_output(data, args.output)
  except Exception as e:  # pylint: disable=broad-except
    print(f"Error executing '{args.command}': {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
