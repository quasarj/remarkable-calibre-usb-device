#!/usr/bin/env python3
import json
import logging
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from .log_helper import log_args_kwargs  # type: ignore
from .rm_data import RemarkableSettings

LOGGER = logging.getLogger("remarkable-calibre-usb-device")

XOCHITL_BASE_FOLDER = "~/.local/share/remarkable/xochitl"
default_prepdir = tempfile.mkdtemp(prefix="resync-")

ssh_socketfile = "/tmp/remarkable-push.socket"
ssh_options2 = ["-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]
ssh_options_str = " ".join(ssh_options2)
ssh_socket_options = f" -S {ssh_socketfile}" if os.name != "nt" else ""
subprocess_creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def ssh_address(settings: RemarkableSettings):
    return f"root@{settings.IP}"
    # FIXME
    return f"root:{settings.SSH_PASSWORD}@{settings.IP}" if settings.SSH_PASSWORD else f"root@{settings.IP}"


@log_args_kwargs
def xochitl_restart_after(settings: RemarkableSettings, seconds=5.0):
    threading.Timer(seconds, lambda: xochitl_restart(settings)).start()


@log_args_kwargs
def xochitl_restart(settings: RemarkableSettings):
    p = subprocess.Popen(
        ["ssh", *ssh_options2, ssh_address(settings), "systemctl restart xochitl"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess_creation_flags,
    )
    p.wait()
    if p.returncode != 0:
        raise SystemError(f"{p.returncode=}, {p.stdout}")


@log_args_kwargs
def _touch_fs(settings: RemarkableSettings):
    """
    Test if ssh is working AND home is writable
    """
    p = subprocess.Popen(
        ["ssh", *ssh_options2, ssh_address(settings), "touch ~/calibre_remarkable_usb_device.touch"],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess_creation_flags,
    )
    p.wait()
    return p.returncode == 0


@log_args_kwargs
def init_metadata(settings: RemarkableSettings):
    p = subprocess.Popen(
        ["ssh", *ssh_options2, ssh_address(settings), f"echo [] > {settings.CALIBRE_METADATA_PATH}"],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess_creation_flags,
    )
    p.wait()
    return p.returncode == 0


@log_args_kwargs
def scp(settings: RemarkableSettings, src_file: str, dest: str):
    p = subprocess.run(
        ["scp", src_file, f"{ssh_address(settings)}:{dest}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess_creation_flags,
    )
    if p.returncode != 0:
        raise RuntimeError(f"returncode={p.returncode}, stdout={p.stdout}")


@log_args_kwargs
def test_connection(settings: RemarkableSettings):
    """
    Test if ssh is working AND home is writable
    """
    try:
        rw_success = _touch_fs(settings)
        if not rw_success:
            p = subprocess.Popen(
                ["ssh", *ssh_options2, ssh_address(settings), "mount -o remount,rw /"],
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess_creation_flags,
            )
            p.wait()
            return p.returncode == 0
        return True
    except:  # noqa: E722
        LOGGER.warning("SSH connection failed", exc_info=True)
        return False


@log_args_kwargs
def rm(settings: RemarkableSettings, paths: list[str]):
    p = subprocess.run(
        ["ssh", *ssh_options2, ssh_address(settings), f"cd {XOCHITL_BASE_FOLDER}; rm {paths} -Rf"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess_creation_flags,
    )
    return p.stdout.strip()


@log_args_kwargs
def cat(settings: RemarkableSettings, file: str):
    p = subprocess.run(
        ["ssh", *ssh_options2, ssh_address(settings), f"cat {file}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess_creation_flags,
    )
    if p.returncode != 0:
        return None

    result = p.stdout.strip()
    LOGGER.debug(f"cat {result=}")
    return result


@log_args_kwargs
def upload_document(
    settings: RemarkableSettings,
    local_path: str,
    visible_name: str,
    file_type: str,
    parent_id: str = "",
    page_count: int = 0,
) -> str:
    """
    Write the full xochitl document layout (.pdf/.epub, .metadata, .content,
    .pagedata + 5 companion dirs) directly via scp. Returns the new doc uuid.
    Much faster than the web upload, and lets us set `parent` at write time
    instead of guessing the uuid back and sed-patching it.
    """
    if file_type not in ("pdf", "epub"):
        raise ValueError(f"unsupported file_type: {file_type!r}")

    doc_id = str(uuid.uuid4())
    now_ms = str(int(time.time() * 1000))

    metadata = {
        "deleted": False,
        "lastModified": now_ms,
        "metadatamodified": False,
        "modified": False,
        "parent": parent_id,
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
        "pageCount": page_count,
        "pages": [],
        "textScale": 1,
        "transform": {
            "m11": 1, "m12": 0, "m13": 0,
            "m21": 0, "m22": 1, "m23": 0,
            "m31": 0, "m32": 0, "m33": 1,
        },
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        doc_path = tmp_path / f"{doc_id}.{file_type}"
        metadata_path = tmp_path / f"{doc_id}.metadata"
        content_path = tmp_path / f"{doc_id}.content"
        pagedata_path = tmp_path / f"{doc_id}.pagedata"

        # Stage by copy so scp can transfer everything in a single call
        # (scp won't rename when given multiple sources + a dir destination).
        shutil.copyfile(local_path, doc_path)
        with open(metadata_path, "w") as fp:
            json.dump(metadata, fp)
        with open(content_path, "w") as fp:
            json.dump(content, fp)
        pagedata_path.touch()

        p = subprocess.run(
            [
                "scp",
                *ssh_options2,
                str(doc_path),
                str(metadata_path),
                str(content_path),
                str(pagedata_path),
                f"{ssh_address(settings)}:{XOCHITL_BASE_FOLDER}/",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess_creation_flags,
        )
        if p.returncode != 0:
            raise RuntimeError(
                f"upload_document scp failed: returncode={p.returncode}, stdout={p.stdout}, stderr={p.stderr}"
            )

    # Companion dirs. xochitl populates them on demand, but they must exist.
    companion_dirs = " ".join(f"{doc_id}{suffix}" for suffix in ("", ".cache", ".highlights", ".textconversion", ".thumbnails"))
    p = subprocess.run(
        ["ssh", *ssh_options2, ssh_address(settings), f"cd {XOCHITL_BASE_FOLDER} && mkdir -p {companion_dirs}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess_creation_flags,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"upload_document mkdir failed: returncode={p.returncode}, stdout={p.stdout}, stderr={p.stderr}"
        )

    return doc_id


@log_args_kwargs
def mkdir(settings: RemarkableSettings, visible_name, parent_id=""):
    file_id = str(uuid.uuid4())
    with tempfile.TemporaryDirectory() as tmp_folder:
        metadata_path = pathlib.Path(tmp_folder, f"{file_id}.metadata")
        content_path = pathlib.Path(tmp_folder, f"{file_id}.content")
        current_timestamp_str = str(int(time.time()))
        # Use json.dumps so names containing quotes/backslashes don't produce
        # invalid metadata on the device.
        metadata = {
            "createdTime": current_timestamp_str,
            "lastModified": current_timestamp_str,
            "parent": parent_id,
            "pinned": False,
            "type": "CollectionType",
            "visibleName": visible_name,
        }
        with open(metadata_path, "w") as fp:
            json.dump(metadata, fp)
        with open(content_path, "w") as fp:
            fp.write('{"tags": []}')

        p = subprocess.run(
            ["scp", str(metadata_path), str(content_path), f"{ssh_address(settings)}:{XOCHITL_BASE_FOLDER}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess_creation_flags,
        )
        LOGGER.debug(p.stdout)
        if p.returncode != 0:
            # Don't return a phantom folder id on failure — callers cache it.
            raise RuntimeError(f"mkdir scp failed: returncode={p.returncode}, stdout={p.stdout}, stderr={p.stderr}")
    return file_id
