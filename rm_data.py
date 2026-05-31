from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import List

from calibre.devices.interface import BookList  # type: ignore

from . import rm_web_interface as rm_web_interface


@dataclass
class RemarkableSettings:
    IP: str

    CALIBRE_METADATA_PATH = "~/.calibre_remarkable_usb_device.metadata"


@dataclass
class RemarkableDeviceDescription:
    def __init__(self, ip):
        self.ip = ip
        # Stable per-device UID so Calibre recognizes the same device across reconnects.
        self.uid = f"remarkable-{ip}"

    def __str__(self) -> str:
        return f"Remarkable on http://{self.ip}, uid={self.uid}"


class RemarkableBookList(BookList):
    def __init__(self, oncard="", prefix="", settings=""):
        super().__init__(oncard, prefix, settings)

    def supports_collections(self):
        return False

    def add_book(self, book, replace_metadata=None):
        self.append(book)

    def remove_book(self, book):
        self.remove(book)

    def get_collections(self, collection_attributes):
        return self

    def json_dumps(self):
        return json.dumps([asdict(x) for x in self], sort_keys=True, default=str)

    @staticmethod
    def json_loads(json_data):
        books = json.loads(json_data)
        rbl = RemarkableBookList()
        for book in books:
            rbl.add_book(RemarkableBook(**book), None)
        return rbl


@dataclass()
class RemarkableBook:
    title: str
    uuid: str
    rm_uuid: str = ""
    authors: list[str] = field(default_factory=list)
    author_sort = ""
    size: int = 0
    datetime: time.struct_time = time.localtime()
    thumbnail = None
    tags: list[str] = field(default_factory=list)
    path: str = "/"

    device_collections: List = field(default_factory=list)

    def __eq__(self, other: object):
        if not isinstance(other, RemarkableBook):
            return NotImplemented
        # Match on either uuid, but only when the matching uuid is non-empty.
        # Otherwise two newly-uploaded books that both have rm_uuid="" would be
        # treated as the same book.
        if self.rm_uuid and self.rm_uuid == other.rm_uuid:
            return True
        if self.uuid and self.uuid == other.uuid:
            return True
        return False

    def __post_init__(self):
        # When RemarkableBook is created from a json blob the argument is a n array and must be converted properly
        self.datetime = time.struct_time(self.datetime)
