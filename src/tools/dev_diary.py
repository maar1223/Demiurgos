#!/usr/bin/env python3
"""Dev diary — appends development entries to the shared Google Sheet.

Credentials: service account JSON at .secrets/demiurgos-diario.json
(spreadsheet shared with the service account email, Editor role).

Usage (from repo root):
  python src/tools/dev_diary.py init            # ensure headers (idempotent)
  python src/tools/dev_diary.py seed            # load historical entries once
  python src/tools/dev_diary.py add --date 2026-08-04 --category bugfix \
      --change "..." --files "a.py, b.tsx" --tests "240 frontend" \
      --status "master local" --notes "..."
  python src/tools/dev_diary.py read [--limit 20]   # read back last rows

Categories: feature | bugfix | UX | refactor | infra | entrega
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_FILE = ROOT / ".secrets" / "demiurgos-diario.json"
# The spreadsheet id is personal data and is never committed to version
# control. It is resolved from the DEMIURGOS_DEV_DIARY_SHEET_ID env var in
# main(); a missing value fails with a clear message (never at import time).
SPREADSHEET_ID: str | None = None
SHEET_NAME = "Diario"

HEADERS = ["Fecha", "Categoría", "Cambio", "Archivos", "Tests", "Estado", "Notas"]

# One-time historical load (jornadas previas, resumidas desde Engram/estado).
HISTORICAL = [
    # --- 2026-08-04 (hoy) ---
    ["2026-08-04", "bugfix",
     "Portada no se mostraba en tarjetas: el backend corría desde 17:09 sin --reload, anterior a los commits de covers. Diagnóstico: /move y /duplicate 404 + tree sin campo portada. Fix: reinicio del API.",
     "api_server.py (solo reinicio)", "198 backend + 240 frontend", "Pendiente push",
     "Lección: el launcher idempotente no detecta código viejo en el puerto"],
    ["2026-08-04", "bugfix",
     "ZeroDivisionError en graph/search (rank_bm25) con entidades sin title/description/tags. Guard any(corpus) + test de regresión. El prefix-match por nombre sigue funcionando.",
     "graph_indexer.py, test_graph_mcp_server.py", "198 backend (197+1)", "Pendiente push",
     "narrative_utils ya estaba protegido con except Exception"],
    ["2026-08-04", "UX",
     "Rediseño de tarjetas de sección: portada full-width con degradado al pie, nombre sobre el degradado, icono de fondo para fichas sin portada, ⋯ dorado sólido en la línea del título (reemplaza al chevron).",
     "SectionCards.tsx, CardMenu.tsx", "240 frontend", "Pendiente push",
     "⋯ no puede anidarse en el botón (HTML inválido) → hermano absoluto alineado a la línea del título"],
    ["2026-08-04", "bugfix",
     "Portadas de retrato cortaban los ojos (object-cover centrado + altura fija). Fix: object-position center 25% + h-44.",
     "SectionCards.tsx", "240 frontend", "Pendiente push",
     "Imágenes de Bira 572x1024 y Rhyz 771x1024 verificadas con System.Drawing"],
    ["2026-08-04", "UX",
     "Badge de conteo de carpetas debajo del nombre (antes lo tapaba) + títulos de tarjeta text-sm (14px).",
     "SectionCards.tsx", "240 frontend", "Pendiente push", ""],
    ["2026-08-04", "bugfix",
     "Sidebar del Asistente IA: botones mic/enviar se perdían en ancho angosto. Fix: min-w-0 en textarea + shrink-0 en botones.",
     "AIAssistantSidebar.tsx", "240 frontend", "Pendiente push",
     "Patrón clásico flexbox: todo item flexible que deba encoger necesita min-w-0"],
    ["2026-08-04", "feature",
     "Paneles laterales redimensionables 1/5-2/5 de pantalla (izquierdo nuevo, derecho con límites proporcionales) + botón modo foco que oculta ambos.",
     "EditorLayout.tsx, WikiEditor.tsx, Icon.tsx", "240 frontend", "Pendiente push",
     "Iconos expand/minimize agregados al set"],
    ["2026-08-04", "UX",
     "Escala tipográfica compacta de herramienta: body 16→14px, h4 20→17px, h1 40→32px, etc. Solo tokens de tipografía (los espaciados no cambian).",
     "tailwind.config.js", "240 frontend", "Pendiente push",
     "El contenido Markdown (prose) no cambió"],
    # --- 2026-08-03 ---
    ["2026-08-03", "feature",
     "Barra de archivo unificada: breadcrumb como chips + botón Importar Imagen con modal (DropZone + estados).",
     "WikiEditor.tsx, ImportImageModal.tsx, DropZone.tsx", "240 frontend", "Entregado (e137f21)", ""],
    ["2026-08-03", "feature",
     "Tarjetas de sección embebidas en la zona central del editor (placeholder eliminado, navegación por carpetas).",
     "SectionCards.tsx", "240 frontend", "Entregado (e137f21)", ""],
    ["2026-08-03", "feature",
     "SDD wiki-card-actions: menú ⋯ por tarjeta (8 acciones), covers resueltas en backend (?covers=true, fallback 8KB), move/duplicate, papelera .papelera/ (sin restore v1), MoveModal, ConfirmDialog, setPortada CRLF-safe con ImagePicker rawMode.",
     "api_server.py, graph_indexer.py, SectionCards/CardMenu/MoveModal/ConfirmDialog/ImagePicker, frontmatter.ts, wiki.ts", "197 backend + 240 frontend", "Entregado",
     "SDD completo: proposal→spec S1-S39→design→tasks T1-T16→verify 38/38 PASS→archive"],
    ["2026-08-03", "entrega",
     "5 PRs encadenados stacked-to-main mergeados en GitHub (#1-#5). Master local = origin = 3ba71d5.",
     "—", "—", "Entregado",
     "Gotcha: gh pr merge --delete-branch cierra PRs hijos → retargetear antes"],
    # --- 2026-08-02 ---
    ["2026-08-02", "feature",
     "Panel derecho redimensionable del editor + 4 endpoints REST del grafo (search/entity/links/status) con EntityGraphIndex lazy. Fix WorldInfo (lore_count/character_count/saga_count mostraban 0).",
     "EditorLayout.tsx, api_server.py, graph_indexer.py", "71 tests", "Entregado",
     "Vibrantes: 67 entidades indexadas"],
    ["2026-08-02", "feature",
     "Chat del Asistente IA con historial de sesiones persistente (localStorage) + grabación de voz Whisper.",
     "AIAssistantSidebar.tsx, useAIAssistantSessions.ts, useWhisper.ts", "240 frontend", "Entregado", ""],
    # --- Jornadas anteriores ---
    ["2026-08-01", "feature",
     "SDD hermes-graph-navigation: MCP server del grafo con 4 tools + 12 tests, integrado en Hermes. Fixes AGENTS.md (protocolo Graph Navigation prescriptivo).",
     "graph_mcp_server.py, AGENTS.md", "12 tests", "Entregado", ""],
    ["2026-07-19", "feature",
     "Bug fixes del asistente Demiurgos (perfil demiurgos-core, timeouts) + menú contextual en árbol de archivos + drag & drop + endpoints crear/borrar carpetas y mover archivos.",
     "frontend, api_server.py", "—", "Entregado",
     "Vite proxy corregido a puerto 8001"],
    ["2026-07-04", "UX",
     "Sistema completo de imágenes: subida, galería, alineación izq/der, portadas full-card con degradado, navegación jerárquica (Volver ↑), _README.md automático, orden directorios-primero.",
     "frontend, api_server.py", "—", "Entregado", ""],
    ["2026-07-03", "feature",
     "Wiki Frontend completo en 3 PRs stacked-to-main: WikiHome + Editor/FileTree/MarkdownViewer + DiffViewer. 71 tests, tsc y build limpios.",
     "frontend/ (scaffold completo)", "71 tests", "Entregado", ""],
    ["2026-07-01", "feature",
     "Wiki Backend: API REST FastAPI con 7 endpoints + 29 tests. Diseños OpenPencil de 3 pantallas.",
     "src/tools/demiurgos-suite/wiki/", "29 tests", "Entregado", ""],
    ["2026-06-29", "feature",
     "SDD wizard-redesign-v2: rediseño visual pixel-perfect (OpenPencil como fuente de verdad), CSS 875→500 líneas, 17 templates con SVG icons.",
     "wizard templates + CSS", "—", "Entregado", "Verify PASS con 11 WARNINGs no bloqueantes"],
    ["2026-06-28", "feature",
     "SDD web-config-ui-onboarding: wizard de onboarding 7 pantallas, i18n 11 idiomas, dashboard de configuración de proveedores LLM.",
     "web-config-ui/", "—", "Entregado", ""],
]


def _service():
    creds = service_account.Credentials.from_service_account_file(
        str(CREDENTIALS_FILE),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds)


def _sheet_meta(svc):
    meta = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == SHEET_NAME:
            return s["properties"]["sheetId"], s["properties"]["title"]
    # Create the sheet if missing.
    req = {"requests": [{"addSheet": {"properties": {"title": SHEET_NAME}}}]}
    svc.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=req).execute()
    return None, SHEET_NAME


def cmd_init(svc) -> None:
    _sheet_meta(svc)
    values = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A1:G1"
    ).execute()
    if values.get("values"):
        print("Headers already present; init idempotent.")
        return
    svc.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:G1",
        valueInputOption="USER_ENTERED",
        body={"values": [HEADERS]},
    ).execute()
    print("Headers written.")


def _append_rows(svc, rows: list[list[str]]) -> None:
    result = svc.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()
    print(f"Appended {result.get('updates', {}).get('updatedRows', 0)} row(s).")


def cmd_seed(svc) -> None:
    existing = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:G"
    ).execute()
    count = len(existing.get("values", []))
    if count > 0:
        print(f"Seed skipped: {count} rows already present.")
        return
    _append_rows(svc, HISTORICAL)


def cmd_add(svc, args) -> None:
    row = [
        args.date,
        args.category,
        args.change,
        args.files or "",
        args.tests or "",
        args.status or "",
        args.notes or "",
    ]
    _append_rows(svc, [row])


def cmd_mark_delivered(svc, date: str) -> None:
    """Set Estado=Entregado on every row matching the given date."""
    result = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:F"
    ).execute()
    rows = result.get("values", [])
    updates = 0
    for i, row in enumerate(rows, start=2):
        if row and row[0] == date and (len(row) < 6 or row[5] != "Entregado"):
            svc.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!F{i}",
                valueInputOption="USER_ENTERED",
                body={"values": [["Entregado"]]},
            ).execute()
            updates += 1
    print(f"Marked {updates} row(s) for {date} as Entregado.")


def cmd_read(svc, limit: int) -> None:
    result = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A1:G"
    ).execute()
    rows = result.get("values", [])
    print(f"{len(rows) - 1} entries:")
    for row in rows[: limit + 1]:
        print(" | ".join(row))


def main() -> int:
    # Windows consoles default to cp1252 and crash on glyphs like "⋯".
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    global SPREADSHEET_ID
    SPREADSHEET_ID = os.environ.get("DEMIURGOS_DEV_DIARY_SHEET_ID", "").strip() or None
    if SPREADSHEET_ID is None:
        print(
            "ERROR: DEMIURGOS_DEV_DIARY_SHEET_ID is not set: export it with your "
            "Google Sheets spreadsheet id (the dev-diary destination sheet).",
            file=sys.stderr,
        )
        return 1

    parser = argparse.ArgumentParser(description="Demiurgos dev diary")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("seed")
    delivered = sub.add_parser("mark-delivered")
    delivered.add_argument("--date", required=True)
    add = sub.add_parser("add")
    add.add_argument("--date", required=True)
    add.add_argument("--category", required=True)
    add.add_argument("--change", required=True)
    add.add_argument("--files", default="")
    add.add_argument("--tests", default="")
    add.add_argument("--status", default="")
    add.add_argument("--notes", default="")
    read = sub.add_parser("read")
    read.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    if not CREDENTIALS_FILE.exists():
        print(f"Missing credentials: {CREDENTIALS_FILE}", file=sys.stderr)
        return 1

    svc = _service()
    if args.command == "init":
        cmd_init(svc)
    elif args.command == "seed":
        cmd_seed(svc)
    elif args.command == "add":
        cmd_add(svc, args)
    elif args.command == "mark-delivered":
        cmd_mark_delivered(svc, args.date)
    elif args.command == "read":
        cmd_read(svc, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
