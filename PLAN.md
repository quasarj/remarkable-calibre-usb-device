# Direct-SCP upload path

## Goal

Replace the slow USB-web-interface upload with a direct SCP that writes the
xochitl on-disk layout ourselves. Keep the web upload as a fallback for users
without SSH.

## What `rm_ssh_upload.sh` does (reference)

For a PDF with a chosen UUID, it writes:

- `{uuid}.pdf` — the document body
- `{uuid}.metadata` — `{deleted, lastModified, parent, pinned, synced, type:
  DocumentType, version, visibleName}`
- `{uuid}.content` — `{fileType: pdf, pageCount, transform, margins,
  orientation, pages: [], extraMetadata: {}, ...}`
- `{uuid}.pagedata` — empty
- five empty companion dirs: `{uuid}`, `{uuid}.cache`, `{uuid}.highlights`,
  `{uuid}.textconversion`, `{uuid}.thumbnails`

Then `mv`s them into `~/.local/share/remarkable/xochitl/` and runs
`systemctl restart xochitl`.

This is the same shape our `rm_ssh.mkdir` already builds for folders
(`CollectionType` + `.content` `{"tags": []}`). New code is a sibling, not a
rewrite.

## New flow in `upload_books`

```
if has_ssh:
    for each (file, metadata):
        ensure folder path exists (unchanged)
        uuid = rm_ssh.upload_document(settings, local_path, visible_name,
                                      parent_id=folder_id_final,
                                      file_type="pdf"|"epub",
                                      page_count=...)
        m.set_user_metadata(RM_UUID, {"#value#": uuid, ...})
    schedule one xochitl_restart_after(5s)   # unchanged
else:
    # current web-upload path, untouched
```

The SSH path stops calling `rm_web_interface.upload_file`,
`get_latest_upload_uuid`, and `sed` — we know our own UUID and we write
`parent` correctly the first time.

## New module function

```python
# rm_ssh.py
def upload_document(
    settings: RemarkableSettings,
    local_path: str,
    visible_name: str,
    file_type: str,           # "pdf" or "epub"
    parent_id: str = "",
    page_count: int | None = None,
) -> str:                     # returns the new document uuid
    """Write a complete xochitl document tree to the device via scp."""
```

Implementation:

1. `doc_id = str(uuid.uuid4())`
2. In a `TemporaryDirectory`, build:
   - `{doc_id}.{file_type}` — copy/hardlink `local_path`
   - `{doc_id}.metadata` — `json.dump(...)`, fields below
   - `{doc_id}.content` — `json.dump(...)`, fields below
   - `{doc_id}.pagedata` — empty file
3. `scp` all four files to `XOCHITL_BASE_FOLDER` in one invocation.
   Check returncode; raise on failure.
4. One `ssh` invocation to `mkdir -p` the five companion dirs:
   `mkdir -p {doc_id} {doc_id}.cache {doc_id}.highlights
   {doc_id}.textconversion {doc_id}.thumbnails` (cwd `XOCHITL_BASE_FOLDER`).
   Check returncode.
5. Return `doc_id`.

### `.metadata` template

```json
{
  "deleted": false,
  "lastModified": "<ms-since-epoch>",
  "metadatamodified": false,
  "modified": false,
  "parent": "<parent_id or ''>",
  "pinned": false,
  "synced": true,
  "type": "DocumentType",
  "version": 1,
  "visibleName": "<visible_name>"
}
```

Built with `json.dumps` so quotes/backslashes in `visible_name` are safe.

### `.content` template (PDF)

Minimal — match the bash script's shape:

```json
{
  "extraMetadata": {},
  "fileType": "pdf",
  "fontName": "",
  "lastOpenedPage": 0,
  "lineHeight": -1,
  "margins": 100,
  "orientation": "portrait",
  "pageCount": <page_count or 1>,
  "pages": [],
  "textScale": 1,
  "transform": {"m11":1,"m12":0,"m13":0,"m21":0,"m22":1,"m23":0,"m31":0,"m32":0,"m33":1}
}
```

### `.content` template (EPUB)

Same shape, with `"fileType": "epub"`. xochitl re-renders pages on first open;
`pageCount` can be 0 and `pages: []`. To be confirmed by smoke test — if epub
needs a different schema we add a branch.

## What we get to delete / simplify

After the SSH path is in production:

- `rm_ssh.get_latest_upload_uuid` — no callers.
- `rm_ssh.sed` — no callers (was only used for the parent fixup).
- The `# FIXME: fails when author has special character ';'` at
  `__init__.py:188` becomes moot.

Don't delete in the same commit as the switch; leave one cycle to roll back.

## Fallback (no SSH)

`upload_books` already branches on `has_ssh = rm_ssh.test_connection(settings)`.
Keep the existing web-upload path for the `not has_ssh` case verbatim. Folders
won't work there, which matches today's behavior.

## Open questions / risks

1. **EPUB on rM2 / rM Paper Pro** — does xochitl accept a bare `.epub` with the
   minimal `.content` we write? rM-SSH-Upload only tests PDF. Need a smoke test
   on the user's actual device before flipping the default.
2. **Firmware schema drift** — the `.content` schema has changed across xochitl
   versions. The minimal shape above has been stable for a while but is not
   guaranteed forever. Mitigation: keep the web fallback reachable behind a
   plugin setting (`prefer_ssh_upload: True`) so a user on a broken firmware
   can flip back without uninstalling.
3. **Partial transfer** — scp isn't atomic across files. If `.metadata` lands
   but `.pdf` doesn't, xochitl shows a broken entry. Acceptable risk for v1;
   could later transfer to a `.tmp` dir and `mv` server-side. The reference
   script doesn't bother.
4. **Page count** — calibre's `Metadata` doesn't always carry `pages`. Default
   to 1; xochitl recomputes on first open. Not worth special-casing.
5. **`get_latest_upload_uuid` race goes away** — we own the UUID. Good.
6. **`sed` shell-injection goes away** — `parent` is set in the JSON we write
   locally. Good.

## Step-by-step

1. **Add `rm_ssh.upload_document`** (no callers yet). Includes the two scp /
   ssh subprocess calls, both returncode-checked.
2. **Add a unit-ish smoke script** (kept out of the plugin) the user can run
   against their device: uploads a small PDF and a small EPUB, asserts they
   appear after xochitl restart. Manual; we don't have a test suite.
3. **Wire it into `upload_books`** behind the existing `has_ssh` branch.
   Stop calling `rm_web_interface.upload_file` / `get_latest_upload_uuid` /
   `sed` in the SSH branch. Web-upload branch unchanged.
4. **User tests** PDF upload (single file, multi-file, into new folder, into
   existing folder, name with quote, name with semicolon).
5. **User tests** EPUB upload (same matrix). If it doesn't work, branch the
   `.content` template or fall back to web for epub specifically.
6. **Follow-up commit**: delete `rm_ssh.sed`, `rm_ssh.get_latest_upload_uuid`,
   and the FIXME comment.

## Not in scope here

- Coalescing `xochitl_restart_after` across batches (separate cleanup).
- Replacing the `tempfile.NamedTemporaryFile(delete=False)` leak in
  `sync_booklists` (separate cleanup).
- Adding a real test suite (separate, larger).
