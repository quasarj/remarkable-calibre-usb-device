# %%
import dataclasses
import json
import logging
from enum import Enum
from urllib import request

LOGGER = logging.getLogger("remarkable-calibre-usb-device")

HEADERS__CONTENT_TYPE__JSON = {"Content-Type": "application/json"}
HEADERS__CHARSET__ISO88591 = {"charset": "ISO-8859-1"}


# %%
class TypeOfDocument(str, Enum):
    DocumentType = "DocumentType"
    CollectionType = "CollectionType"


@dataclasses.dataclass
class Document:
    # Bookmarked
    # CurrentPage': 6,
    ID: str
    #'ModifiedClient': '2024-09-26T20:25:19.379Z',
    Parent: str
    Type: str
    VissibleName: str
    fileType: str

    @classmethod
    def parse(cls, d: dict):
        return Document(
            d["ID"],
            d["Parent"],
            str(d.get("Type")),
            str(d.get("VissibleName", "")),
            str(d.get("fileType")),
        )


@dataclasses.dataclass
class Node:
    children: list["ChildNode"]

    @classmethod
    def new_empty(cls):
        return Node([])

    def ls_recursive(self: "Node"):
        result = []
        for c in self.children:
            if c.document.Type == TypeOfDocument.CollectionType:
                ls_children = list(map(lambda path: f"{c.visible_name}/{path}", c.ls_recursive()))
                result.extend(ls_children)
            else:
                result.append(c.visible_name)
        return result

    def ls_uuid(self: "Node"):
        result = []
        for c in self.children:
            if c.document.Type == TypeOfDocument.CollectionType:
                result.extend(c.ls_uuid())
            else:
                result.append(c.document.ID)
        return result

    def ls_dir_recursive(self: "Node"):
        result = []
        for c in self.children:
            if c.document.Type == TypeOfDocument.CollectionType:
                result.append(c.visible_name)
                ls_children = list(map(lambda path: f"{c.visible_name}/{path}", c.ls_dir_recursive()))
                result.extend(ls_children)
        return result

    def ls_dir_recursive_dict(self: "Node"):
        result = {}
        for c in self.children:
            if c.document.Type == TypeOfDocument.CollectionType:
                result[c.visible_name] = c.document.ID
                result.update({f"{c.visible_name}/{name}": id for name, id in c.ls_dir_recursive_dict().items()})
        return result

    def walk_with_parent(self: "Node", my_id: str = ""):
        """Yield (child_node, parent_id) for every ChildNode in this tree."""
        for c in self.children:
            yield c, my_id
            yield from c.walk_with_parent(c.document.ID)


@dataclasses.dataclass
class ChildNode(Node):
    document: Document

    @property
    def visible_name(self):
        return self.document.VissibleName


def query_document(ip, path_id, **kwargs):
    base_url = f"http://{ip}"
    headers = {}
    headers.update(HEADERS__CONTENT_TYPE__JSON)
    headers.update(HEADERS__CHARSET__ISO88591)
    url = f"{base_url}/documents/{path_id}"
    req = request.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)
    with request.urlopen(req, **kwargs) as conn:
        return json.loads(conn.read())


def check_connection(ip: str):
    try:
        query_document(ip, "", timeout=2)
        return True
    except Exception as e:
        LOGGER.warning("Unable to connect to remarkable", exc_info=True)
        return False


def query_tree(ip, path_id):
    document_list_jsond = query_document(ip, path_id)
    root = Node.new_empty()
    id_to_obj = {path_id: root}
    documents: list[Document] = list(sorted((Document.parse(r) for r in document_list_jsond), key=lambda d: d.Parent))
    for d in documents:
        id_to_obj[d.ID] = d
        node = ChildNode([], document=d)
        id_to_obj[d.Parent].children.append(node)
        if d.Type == TypeOfDocument.CollectionType:
            cc = query_tree(ip, d.ID).children
            node.children.extend(cc)

    return root
