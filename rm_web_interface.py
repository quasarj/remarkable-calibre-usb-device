# %%
import dataclasses
import io
import json
import logging
import mimetypes
import uuid
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


class MultiPartForm:
    """Accumulate the data to be used when posting a form."""

    def __init__(self):
        self.form_fields = []
        self.files = []
        # Use a large random byte string to separate
        # parts of the MIME data.
        self.boundary = ("------" + uuid.uuid4().hex).encode("utf-8")
        return

    def get_content_type(self):
        return "multipart/form-data; boundary={}".format(self.boundary.decode("utf-8"))

    def add_field(self, name, value):
        """Add a simple field to the form data."""
        self.form_fields.append((name, value))

    def add_file(self, fieldname, filename, fileHandle, mimetype=None):
        """Add a file to be uploaded."""
        body = fileHandle.read()
        if mimetype is None:
            mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        self.files.append((fieldname, filename, mimetype, body))
        return

    @staticmethod
    def _form_data(name):
        return ('Content-Disposition: form-data; name="{}"\r\n').format(name).encode("utf-8")

    @staticmethod
    def _attached_file(name, filename):
        return (
            # ('Content-Disposition: file; name="{}"; filename="{}"\r\n')
            ('Content-Disposition: form-data; name="{}"; filename="{}"\r\n')
            .format(name, filename)
            .encode("utf-8")
        )

    @staticmethod
    def _content_type(ct):
        return "Content-Type: {}\r\n".format(ct).encode("utf-8")

    def __bytes__(self):
        """Return a byte-string representing the form data,
        including attached files.
        """
        buffer = io.BytesIO()
        boundary = b"--" + self.boundary + b"\r\n"

        # Add the form fields
        for name, value in self.form_fields:
            buffer.write(boundary)
            buffer.write(self._form_data(name))
            buffer.write(b"\r\n")
            buffer.write(value.encode("utf-8"))
            buffer.write(b"\r\n")

        # Add the files to upload
        for f_name, filename, f_content_type, body in self.files:
            buffer.write(boundary)
            buffer.write(self._attached_file(f_name, filename))
            buffer.write(self._content_type(f_content_type))
            buffer.write(b"\r\n")
            buffer.write(body)
            buffer.write(b"\r\n")

        buffer.write(b"--" + self.boundary + b"--\r\n")
        return buffer.getvalue()


# %%


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


# class NonRaisingHTTPErrorProcessor(request.HTTPErrorProcessor):
#    http_response = https_response = lambda self, request, response: response


def upload_file(ip, local_path, folder_id, visible_name, **kwargs):
    base_url = f"http://{ip}"
    headers = {
        "Origin": f"{base_url}",
        "Accept": "*/*",
        "Referer": f"{base_url}/",
        "Connection": "keep-alive",
    }

    # position pointer on folder
    resp = query_document(ip, folder_id)
    LOGGER.debug(f"{resp=}")

    # upload
    with open(local_path, "rb") as fp:
        url = f"{base_url}/upload"
        form = MultiPartForm()
        form.add_file("file", visible_name, fp)
        data = bytes(form)
        req = request.Request(url, data=data)
        for k, v in headers.items():
            req.add_header(k, v)
        req.add_header("Content-Length", len(data))
        req.add_header("Content-Type", form.get_content_type())
        # opener = request.build_opener(NonRaisingHTTPErrorProcessor)
        # with opener.open(req, **kwargs) as conn:
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
