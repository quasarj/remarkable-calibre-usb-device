#!/usr/bin/env bash
# Upload a single PDF or EPUB to a Remarkable tablet by writing the xochitl
# on-disk layout directly (scp + ssh). Used to validate the schema the
# calibre plugin's planned direct-SCP path will write.
#
# Usage:
#   ./upload_book.sh <file.pdf|.epub> [visible_name] [parent_uuid]
#
# Env:
#   RM_HOST  (default: 10.11.99.1)
#
# Requires SSH key auth to root@RM_HOST already set up.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <file.pdf|.epub> [visible_name] [parent_uuid]" >&2
    exit 1
fi

src="$1"
visible_name="${2:-$(basename "$src" | sed 's/\.[^.]*$//')}"
parent_uuid="${3:-}"
host="${RM_HOST:-10.11.99.1}"
ssh_addr="root@${host}"
xochitl_dir="/home/root/.local/share/remarkable/xochitl"

if [ ! -f "$src" ]; then
    echo "File not found: $src" >&2
    exit 1
fi

ext_lower="$(echo "${src##*.}" | tr '[:upper:]' '[:lower:]')"
case "$ext_lower" in
    pdf|epub) file_type="$ext_lower" ;;
    *) echo "Unsupported extension: .$ext_lower (need .pdf or .epub)" >&2; exit 1 ;;
esac

doc_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
now_ms="$(( $(date -u +%s) * 1000 ))"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

echo "doc_id        = $doc_id"
echo "visible_name  = $visible_name"
echo "file_type     = $file_type"
echo "parent        = ${parent_uuid:-<root>}"
echo "host          = $host"
echo

cp "$src" "$staging/${doc_id}.${file_type}"

# Build the JSON via python so visibleName with quotes/backslashes/unicode
# is encoded safely — the same way the plugin will do it.
python3 - "$staging" "$doc_id" "$visible_name" "$parent_uuid" "$file_type" "$now_ms" <<'PY'
import json, os, sys
staging, doc_id, visible_name, parent, file_type, now_ms = sys.argv[1:]

metadata = {
    "deleted": False,
    "lastModified": now_ms,        # string in the reference script; xochitl accepts both
    "metadatamodified": False,
    "modified": False,
    "parent": parent,
    "pinned": False,
    "synced": True,
    "type": "DocumentType",
    "version": 1,
    "visibleName": visible_name,
}

content = {
    "extraMetadata": {},
    "fileType": file_type,
    "fontName": "",
    "lastOpenedPage": 0,
    "lineHeight": -1,
    "margins": 100,
    "orientation": "portrait",
    "pageCount": 0,
    "pages": [],
    "textScale": 1,
    "transform": {
        "m11": 1, "m12": 0, "m13": 0,
        "m21": 0, "m22": 1, "m23": 0,
        "m31": 0, "m32": 0, "m33": 1,
    },
}

with open(os.path.join(staging, f"{doc_id}.metadata"), "w") as f:
    json.dump(metadata, f, indent=2)
with open(os.path.join(staging, f"{doc_id}.content"), "w") as f:
    json.dump(content, f, indent=2)
open(os.path.join(staging, f"{doc_id}.pagedata"), "w").close()
PY

echo "--- staged files ---"
ls -la "$staging"
echo

ssh_opts=(-o StrictHostKeyChecking=no -o BatchMode=yes)

echo "--- scp to ${xochitl_dir}/ ---"
scp "${ssh_opts[@]}" \
    "$staging/${doc_id}.${file_type}" \
    "$staging/${doc_id}.metadata" \
    "$staging/${doc_id}.content" \
    "$staging/${doc_id}.pagedata" \
    "${ssh_addr}:${xochitl_dir}/"

echo
echo "--- creating companion dirs ---"
ssh "${ssh_opts[@]}" "$ssh_addr" "cd '${xochitl_dir}' && mkdir -p '${doc_id}' '${doc_id}.cache' '${doc_id}.highlights' '${doc_id}.textconversion' '${doc_id}.thumbnails'"

echo
echo "--- restarting xochitl ---"
ssh "${ssh_opts[@]}" "$ssh_addr" "systemctl restart xochitl"

echo
echo "Done. Uploaded '${visible_name}' as ${doc_id}"
echo "If it doesn't appear or shows a broken thumbnail, capture:"
echo "  ssh ${ssh_addr} 'journalctl -u xochitl --since \"1 minute ago\" | tail -100'"
