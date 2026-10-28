"""MFC CArchive structure of .PRS files: walk, check, repair, rebuild.

RPM saves a personality with MFC's ``CArchive``.  Two rules of that format
matter whenever anything is added to or removed from a personality:

* Every class and every object takes the next index in the archive's map
  (index 0 is the null object, so the first class is 1).  The first object
  of a class is written as ``FF FF`` + schema + name, and every later object
  of that class as the 2-byte tag ``0x8000 | class_index``.  Older QuickPRS
  code called these tags "separators" and "set markers" and copied them from
  the source file, which only works while nothing in front of them changes.
* Every list is written as a WORD count followed by its objects, so a list's
  count sits in the 2 bytes in front of its first object.

Adding one talkgroup therefore moves the index of every class first written
after it, so every later tag must change, and the count in front of the
list must follow its length.  RPM's loader (``CArchive::ReadObject``) throws
``badIndex`` or ``badClass`` on a tag that does not name the expected class,
and ``badSchema`` on a class written with the wrong schema, so such a file
does not open in RPM.

This module reads a file into a :class:`Document`, a tree of :class:`Obj`
and :class:`ObjList` nodes that keeps every byte, and writes it back with
fresh tags and counts, so edits made on the tree come out right by
construction.  :func:`check` lists the tags and counts a file has wrong and
:func:`repair` rewrites them.

Document layout, in the order RPM writes it::

    CPersonality  header fields and radio type list
                  systems list           (CConvSystem / CP25TrkSystem /
                                          CP25ConvSystem; P25 trunked
                                          systems hold their ECC list)
                  trunk sets list        (CTrunkSet -> CTrunkChannel)
                  6 bytes
                  conv sets list         (CConvSet -> CConvChannel)
                  options list           (CGenRadioOpts, CP25tWanOpts ...)
                  personality name, user, band limits, radio type
                  group sets list        (CP25GroupSet -> CP25Group)
                  P25 conv sets list     (CP25ConvSet -> CP25ConvChannel)
                  a list that is empty in every file seen so far
                  IDEN sets list         (CIdenDataSet -> CDefaultIdenElem)
                  remaining fields (XML platform config, terminator)
"""

from dataclasses import dataclass, field
import struct

NULL_TAG = 0x0000
NEW_CLASS_TAG = 0xFFFF
CLASS_TAG = 0x8000
BIG_OBJECT_TAG = 0x7FFF

# Class schemas exactly as RPM 14 writes them (one value per class across
# every RPM-saved file in the test corpus).  MFC refuses a class whose
# schema does not match (CArchiveException::badSchema).
SCHEMAS = {
    "CPersonality": 133,
    "CConvSystem": 141,
    "CP25TrkSystem": 141,
    "CP25ConvSystem": 141,
    "CPreferredSystemTableEntry": 100,
    "CTrunkSet": 100,
    "CTrunkChannel": 101,
    "CConvSet": 101,
    "CConvChannel": 106,
    "CP25GroupSet": 106,
    "CP25Group": 106,
    "CP25ConvSet": 102,
    "CP25ConvChannel": 113,
    "CIdenDataSet": 102,
    "CDefaultIdenElem": 102,
    "CAccessoryDevice": 101,
    "CAlertOpts": 103,
    "CConvScanOpts": 101,
    "CCustomScanList": 101,
    "CDTMFOpts": 101,
    "CDataOpts": 105,
    "CDiagnosticOpts": 100,
    "CDisplayOpts": 102,
    "CGEstarOpts": 101,
    "CGenRadioOpts": 113,
    "CICall": 101,
    "CIgnitionOpts": 101,
    "CKeypadCtrlOpts": 101,
    "CMdcOpts": 103,
    "CMmsOpts": 100,
    "CMrkOpts": 102,
    "CNetworkOpts": 101,
    "CP25TrkWan": 100,
    "CP25tWanOpts": 100,
    "CPhoneCall": 101,
    "CPowerUpOpts": 104,
    "CPrgrmICall": 100,
    "CPrgrmPhoneCall": 100,
    "CProFileOpts": 100,
    "CProSoundOpts": 100,
    "CProgButtons": 100,
    "CScanOpts": 100,
    "CSecurityPolicy": 100,
    "CSndcpOpts": 100,
    "CStatus": 101,
    "CSupervisoryOpts": 103,
    "CSystemScanOpts": 100,
    "CT99": 100,
    "CTimerOpts": 104,
    "CType99Opts": 100,
    "CVgOpts": 104,
    "CVoiceAnnunciation": 101,
}

# Data bytes of option objects that hold no other objects, measured on
# RPM-saved files.
OPTION_DATA_SIZES = {
    "CGenRadioOpts": 88,
    "CCustomScanList": 8,
    "CDTMFOpts": 56,
    "CTimerOpts": 82,
    "CPowerUpOpts": 36,
    "CDataOpts": 41,
    "CSupervisoryOpts": 36,
    "CScanOpts": 33,
    "CConvScanOpts": 30,
    "CAlertOpts": 19,
    "CProSoundOpts": 28,
    "CKeypadCtrlOpts": 20,
    "CIgnitionOpts": 10,
    "CMrkOpts": 16,
    "CDiagnosticOpts": 8,
    "CNetworkOpts": 38,
    "CDisplayOpts": 37,
    "CGEstarOpts": 35,
    "CMmsOpts": 13,
    "CSndcpOpts": 8,
    "CAccessoryDevice": 8,
    "CSystemScanOpts": 24,
    "CSecurityPolicy": 2,
    "CVgOpts": 54,
    "CVoiceAnnunciation": 12,
    "CStatus": 7,
    "CProFileOpts": 3,
    "CMdcOpts": 24,
    "CProgButtons": 2,
}

SYSTEM_TYPE_CLASSES = {
    0x01: "CConvSystem",
    0x03: "CP25ConvSystem",
    0x05: "CP25TrkSystem",
}
SYSTEM_CLASSES = frozenset(SYSTEM_TYPE_CLASSES.values())

# set list name -> (set class, item class, fixed item size or None)
SET_LISTS = {
    "trunk sets": ("CTrunkSet", "CTrunkChannel", 23),
    "conv sets": ("CConvSet", "CConvChannel", None),
    "group sets": ("CP25GroupSet", "CP25Group", None),
    "P25 conv sets": ("CP25ConvSet", "CP25ConvChannel", None),
    "IDEN sets": ("CIdenDataSet", "CDefaultIdenElem", 15),
}

CONV_SET_META_SIZE = 60   # bytes after a conventional set's name
MAX_SET_PADDING = 64      # extra bytes searched for after that (issue #1)
MAX_ITEMS = 2048          # sanity bound on a probed count


class WalkError(ValueError):
    """The bytes do not follow the archive layout QuickPRS knows."""


# ── document tree ─────────────────────────────────────────────────────

@dataclass
class Obj:
    """One archived object: its class and its data.

    ``parts`` holds the object's data in order: plain ``bytes`` and the
    :class:`ObjList` s nested in it.  Headers, tags and counts are not
    stored; :func:`serialize` writes them.
    """
    cls: str
    parts: list = field(default_factory=list)

    def lists(self):
        return [p for p in self.parts if isinstance(p, ObjList)]

    def data(self):
        """The object's bytes with nested lists left out."""
        return b"".join(p for p in self.parts if isinstance(p, bytes))


@dataclass
class ObjList:
    """A list of objects.  ``counted`` lists carry a WORD count in front;
    fixed arrays (the three CT99 objects) do not.  ``None`` items are NULL
    object pointers."""
    name: str
    items: list = field(default_factory=list)
    counted: bool = True


@dataclass
class TagSite:
    offset: int
    class_name: str
    value: int          # index the file holds


@dataclass
class CountSite:
    offset: int
    name: str
    value: int          # count the file holds
    items: int          # objects the walk found


@dataclass
class Document:
    """A whole personality as an object tree (see the module docstring)."""
    root: Obj
    schemas: dict = field(default_factory=dict)

    def list(self, name):
        """The top-level list called ``name`` ("trunk sets", "systems" ...)."""
        for p in self.root.parts:
            if isinstance(p, ObjList) and p.name == name:
                return p
        raise KeyError(name)

    def option(self, cls):
        """The option object of class ``cls``, or None."""
        for o in self.list("options").items:
            if o is not None and o.cls == cls:
                return o
        return None

    def to_bytes(self):
        return serialize(self)


@dataclass
class WalkReport:
    tags: list = field(default_factory=list)
    counts: list = field(default_factory=list)
    class_index: dict = field(default_factory=dict)
    class_order: list = field(default_factory=list)
    padding: list = field(default_factory=list)   # (offset, bytes)
    entries: int = 0
    tail_offset: int = 0


# ── reader ────────────────────────────────────────────────────────────

class _Walker:
    """Reads the archive in RPM's Serialize order and builds the tree.

    With ``lenient`` set, list lengths come from what is actually there
    (each item is recognised by its object header) rather than from the
    stored count, so files whose counts were left stale can still be read
    and repaired; the stored counts are kept in the report for checking.
    """

    def __init__(self, data, lenient):
        self.d = bytes(data)
        self.pos = 0
        self.lenient = lenient
        self.next_index = 1
        self.kinds = {}        # index -> ("class" | "obj", class name)
        self.schemas = {}
        self.r = WalkReport()

    # primitives

    def _need(self, n, what):
        if n < 0 or self.pos + n > len(self.d):
            raise WalkError(f"file ends inside {what} at 0x{self.pos:x}")

    def take(self, n, what="data"):
        self._need(n, what)
        b = self.d[self.pos:self.pos + n]
        self.pos += n
        return b

    def u8(self, what="byte"):
        return self.take(1, what)[0]

    def u16(self, what="word"):
        return struct.unpack("<H", self.take(2, what))[0]

    def cstring(self, what="string"):
        """Skip an MFC CString; return its raw bytes (prefix included)."""
        start = self.pos
        n = self.u8(what)
        wide = False
        if n == 0xFF:
            n = self.u16(what)
            if n == 0xFFFE:                 # Unicode marker
                wide = True
                n = self.u8(what)
                if n == 0xFF:
                    n = self.u16(what)
            if n == 0xFFFF:
                n = struct.unpack("<I", self.take(4, what))[0]
        self.take(n * 2 if wide else n, what)
        return self.d[start:self.pos]

    def _w(self, pos):
        if pos + 2 > len(self.d):
            return None
        return struct.unpack_from("<H", self.d, pos)[0]

    def _class_at(self, pos):
        """Class name of a new-class header at ``pos``, else None."""
        if self._w(pos) != NEW_CLASS_TAG or pos + 6 > len(self.d):
            return None
        n = self._w(pos + 4)
        raw = self.d[pos + 6:pos + 6 + n]
        if not 1 <= n <= 64 or len(raw) != n or raw[:1] != b"C":
            return None
        if not raw.replace(b"_", b"").isalnum():
            return None
        return raw.decode("ascii")

    def _tag_at(self, pos):
        # Only the high bit is checked: a stale tag can hold any index, even
        # one past the current map size after objects were removed.
        w = self._w(pos)
        return (w is not None and bool(w & CLASS_TAG) and
                w not in (NEW_CLASS_TAG, BIG_OBJECT_TAG))

    def _object_at(self, pos, classes):
        name = self._class_at(pos)
        if name is not None:
            return name in classes
        return bool(self._tag_at(pos))

    def _printable_cstring_at(self, pos, max_len=64):
        if pos >= len(self.d):
            return False
        n = self.d[pos]
        raw = self.d[pos + 1:pos + 1 + n]
        return n <= max_len and len(raw) == n and all(
            32 <= c < 127 for c in raw)

    # objects

    def _index(self, kind, name):
        self.kinds[self.next_index] = (kind, name)
        self.next_index += 1

    def header(self, expect):
        """Read an object header; return the class name (None for NULL).

        A tag is recorded together with the class the layout puts at this
        spot, so a stale tag value cannot send the walk the wrong way.
        """
        start = self.pos
        w = self.u16("object header")
        if w == NULL_TAG:
            return None
        if w == NEW_CLASS_TAG:
            schema = self.u16("class schema")
            n = self.u16("class name length")
            raw = self.take(n, "class name")
            name = raw.decode("ascii", "replace")
            if self._class_at(start) is None:
                raise WalkError(f"bad class header at 0x{start:x}")
            if name in self.r.class_index:
                raise WalkError(f"class {name} defined twice (0x{start:x})")
            if expect is not None and name not in expect:
                raise WalkError(
                    f"expected {' or '.join(sorted(expect))} at 0x{start:x},"
                    f" found new class {name}")
            self.schemas[name] = schema
            self.r.class_index[name] = self.next_index
            self.r.class_order.append(name)
            self._index("class", name)
            self._index("obj", name)
            return name
        if w == BIG_OBJECT_TAG or not w & CLASS_TAG:
            raise WalkError(
                f"unexpected word 0x{w:04x} at 0x{start:x} where an object "
                f"header was expected")
        if expect is not None and len(expect) == 1:
            name = next(iter(expect))
        else:
            kind = self.kinds.get(w & ~CLASS_TAG)
            if not kind or kind[0] != "class" or (
                    expect is not None and kind[1] not in expect):
                raise WalkError(
                    f"cannot tell which class the tag 0x{w:04x} at "
                    f"0x{start:x} names")
            name = kind[1]
        if name not in self.r.class_index:
            raise WalkError(
                f"tag at 0x{start:x} refers to {name}, which is not defined "
                f"before it")
        self.r.tags.append(TagSite(start, name, w & ~CLASS_TAG))
        self._index("obj", name)
        return name

    def counted(self, name, more, read_item):
        """Read a WORD-counted list; ``more()`` says whether another item
        starts at the cursor (used when lenient)."""
        site = self.pos
        stored = self.u16(f"{name} count")
        lst = ObjList(name)
        if self.lenient:
            while more():
                if len(lst.items) >= MAX_ITEMS:
                    raise WalkError(f"runaway {name} list at 0x{site:x}")
                lst.items.append(read_item())
        else:
            for _ in range(stored):
                lst.items.append(read_item())
        self.r.counts.append(CountSite(site, name, stored, len(lst.items)))
        return lst

    # document

    def document(self):
        if self.header({"CPersonality"}) != "CPersonality":
            raise WalkError("file does not start with CPersonality")
        start = self.pos
        kv = self.u8("personality header")
        self.take(kv + 4, "personality header")
        for _ in range(6):
            self.cstring("personality string")
        n_types = self.u16("radio type list")
        self.take(2 * n_types, "radio type list")
        parts = [self.d[start:self.pos]]

        parts.append(self.counted("systems", self._system_follows,
                                  self.system))
        parts.append(self.set_list("trunk sets"))
        parts.append(self.take(6, "fields after trunk sets"))
        parts.append(self.set_list("conv sets"))
        parts.append(self.counted("options", self._option_follows,
                                  self.option))
        start = self.pos
        self.cstring("personality name")
        self.take(2, "personality fields")
        self.cstring("user name")
        self.take(2 + 32 + 2, "band limits")
        parts.append(self.d[start:self.pos])
        parts.append(self.set_list("group sets"))
        parts.append(self.set_list("P25 conv sets"))
        site = self.pos
        if self.u16("list after P25 conv sets"):
            raise WalkError(
                f"unknown non-empty list after the P25 conv sets at "
                f"0x{site:x}")
        parts.append(ObjList("unknown list"))
        parts.append(self.set_list("IDEN sets"))
        self.r.tail_offset = self.pos
        self._check_tail()
        parts.append(self.d[self.pos:])
        self.r.entries = self.next_index - 1
        return Document(Obj("CPersonality", parts), dict(self.schemas))

    def _check_tail(self):
        """Only plain fields may follow the IDEN sets; an object there would
        be one this walker does not know, whose tags it could not fix."""
        pos = self.pos
        while True:
            pos = self.d.find(b"\xff\xff", pos)
            if pos < 0:
                return
            name = self._class_at(pos)
            if name is not None and len(name) >= 4:
                raise WalkError(
                    f"unknown object {name} after the IDEN sets at 0x{pos:x}")
            pos += 1

    # systems

    def _system_follows(self):
        name = self._class_at(self.pos)
        if name is not None:
            return name in SYSTEM_CLASSES
        if not self._tag_at(self.pos):
            return False
        p = self.pos + 2
        if not self._printable_cstring_at(p):
            return False
        p += 1 + self.d[p]
        return (p + 3 <= len(self.d) and self.d[p] in SYSTEM_TYPE_CLASSES
                and self.d[p + 1:p + 3] == b"\xff\xff")

    def system(self):
        start = self.pos
        if self._w(self.pos) == NEW_CLASS_TAG:
            cls = self.header(SYSTEM_CLASSES)
            data_start = self.pos
            self.cstring("system name")
            stype = self.u8("system type")
            if SYSTEM_TYPE_CLASSES.get(stype) != cls:
                raise WalkError(
                    f"system at 0x{start:x}: class {cls} with type byte "
                    f"0x{stype:02x}")
        else:
            # A tag only says "a system"; the type byte after the name says
            # which class, so a stale tag value cannot mislead the walk.
            w = self.u16("system header")
            if not w & CLASS_TAG or w in (NEW_CLASS_TAG, BIG_OBJECT_TAG):
                raise WalkError(f"expected a system object at 0x{start:x}")
            data_start = self.pos
            self.cstring("system name")
            stype = self.u8("system type")
            cls = SYSTEM_TYPE_CLASSES.get(stype)
            if cls is None:
                raise WalkError(
                    f"unknown system type 0x{stype:02x} at 0x{start:x}")
            if cls not in self.r.class_index:
                raise WalkError(
                    f"system at 0x{start:x} is tagged, but no {cls} is "
                    f"defined before it")
            self.r.tags.append(TagSite(start, cls, w & ~CLASS_TAG))
            self._index("obj", cls)
        if self.u16("system config marker") != 0xFFFF:
            raise WalkError(f"system at 0x{start:x}: config lacks FFFF")
        self.take(42, "system config prefix")
        self.cstring("system long name")
        if cls == "CP25TrkSystem":
            self.take(15, "system flags")
            self.cstring("trunk set name")
            self.cstring("group set name")
            self.take(12 + 4 + 12 + 6 + 2 + 4, "system ids")
            self.cstring("WAN name")
            self.take(44, "WAN config")
            self.cstring("WAN name")
            self.take(13 + 4 + 4, "unit ids and band limits")
            if self.u8("ECC marker") != 0x06:
                raise WalkError(f"system at 0x{start:x}: ECC marker missing")
            head = self.d[data_start:self.pos]
            ecc = self.counted(
                "ECC entries",
                lambda: self._object_at(self.pos,
                                        {"CPreferredSystemTableEntry"}),
                lambda: self.fixed("CPreferredSystemTableEntry", 13))
            rest = self.pos
            self.take(4, "fields after ECC list")
            self.cstring("IDEN set name")
            self.take(63, "system tail")
            return Obj(cls, [head, ecc, self.d[rest:self.pos]])
        if cls == "CConvSystem":
            self.take(12, "conv system fields")
            self.cstring("conv set name")
            self.take(3 + 4, "conv system fields")
        else:
            self.take(5 + 4, "P25 conv system fields")
            self.cstring("P25 conv set name")
            self.take(27 + 6 + 2 + 26, "P25 conv system fields")
        return Obj(cls, [self.d[data_start:self.pos]])

    def fixed(self, cls, size):
        name = self.header({cls})
        if name is None:
            return None
        return Obj(cls, [self.take(size, cls)])

    # sets

    def set_list(self, name):
        set_cls, item_cls, _ = SET_LISTS[name]
        return self.counted(name, lambda: self._set_follows(name),
                            lambda: self.set_object(name))

    def _set_follows(self, name):
        set_cls, item_cls, _ = SET_LISTS[name]
        cname = self._class_at(self.pos)
        if cname is not None:
            return cname == set_cls
        if not self._tag_at(self.pos):
            return False
        n = self._w(self.pos + 2)
        if n is None or n > MAX_ITEMS:
            return False
        return n == 0 or self._object_at(self.pos + 4, {item_cls})

    def set_object(self, name):
        set_cls, item_cls, size = SET_LISTS[name]
        self.header({set_cls})
        items = self.counted(
            "items", lambda: self._object_at(self.pos, {item_cls}),
            lambda: self.fixed(item_cls, size) if size else
            self.variable_item(item_cls))
        meta_start = self.pos
        getattr(self, "_meta_" + set_cls)()
        return Obj(set_cls, [items, self.d[meta_start:self.pos]])

    def variable_item(self, cls):
        if self.header({cls}) is None:
            return None
        start = self.pos
        if cls == "CConvChannel":
            self.cstring("short name")
            self.take(16, "frequencies")
            self.cstring("tx tone")
            self.cstring("rx tone")
            self.take(4 + 48 + 10, "channel fields")
            self.cstring("long name")
            self.take(7, "channel trailer")
        elif cls == "CP25Group":
            self.cstring("group name")
            self.take(2 + 12 + 7, "group fields")
            self.cstring("group long name")
            self.take(4, "group tail")
        else:  # CP25ConvChannel
            self.cstring("short name")
            self.take(16, "frequencies")
            self.cstring("tx tone")
            self.cstring("rx tone")
            self.take(8 + 22, "channel fields")
            self.cstring("long name")
            self.take(20, "channel trailer")
        return Obj(cls, [self.d[start:self.pos]])

    def _meta_CTrunkSet(self):
        self.cstring("trunk set name")
        self.take(2 + 32 + 13, "trunk set fields")

    def _meta_CConvSet(self):
        self.cstring("conv set name")
        self.take(CONV_SET_META_SIZE, "conv set fields")
        if self._after_conv_set():
            return
        # Issue #1: some RPM files carry a few more bytes here.  Find where
        # the next set (or the options list) starts and keep the bytes.
        base = self.pos
        for k in range(1, MAX_SET_PADDING + 1):
            self.pos = base + k
            if self.pos + 2 <= len(self.d) and self._after_conv_set():
                self.r.padding.append((base, self.d[base:self.pos]))
                return
        self.pos = base
        raise WalkError(f"cannot find the end of the conv set at 0x{base:x}")

    def _after_conv_set(self):
        """True when the next conv set or the options list starts here."""
        if self._set_follows("conv sets"):
            return True
        n = self._w(self.pos)            # the options list count
        if n is None or n > 200:
            return False
        if self._class_at(self.pos + 2) is not None:
            return True                  # first option (count may be stale)
        return n == 0 and self._doc_fields_at(self.pos + 2)

    def _doc_fields_at(self, pos):
        """Personality name, 2 bytes, user name, then 0E 00 (no options)."""
        if not self._printable_cstring_at(pos, 255):
            return False
        pos += 1 + self.d[pos] + 2
        if not self._printable_cstring_at(pos, 255):
            return False
        pos += 1 + self.d[pos]
        return self.d[pos:pos + 2] == b"\x0e\x00"

    def _meta_CP25GroupSet(self):
        self.cstring("group set name")
        self.take(16, "group set fields")

    def _meta_CP25ConvSet(self):
        self.cstring("P25 conv set name")
        self.take(2 + 32, "P25 conv set fields")
        self.cstring("P25 conv group reference")
        self.take(13, "P25 conv set fields")

    def _meta_CIdenDataSet(self):
        self.cstring("IDEN set name")
        self.take(2, "IDEN set fields")

    # options

    def _option_follows(self):
        name = self._class_at(self.pos)
        if name is not None:
            return name not in SYSTEM_CLASSES
        # The options are followed by the personality name (a CString of
        # ASCII), which can never look like a tag.
        return self._tag_at(self.pos)

    def option(self):
        start = self.pos
        cls = self.header(None)
        if cls is None:
            return None
        if cls == "CP25tWanOpts":
            return Obj(cls, [self.counted(
                "WAN entries",
                lambda: self._object_at(self.pos, {"CP25TrkWan"}),
                self._wan_entry)])
        if cls == "CPrgrmICall":
            return Obj(cls, [self.counted(
                "individual calls",
                lambda: self._object_at(self.pos, {"CICall"}),
                lambda: self.fixed("CICall", 22))])
        if cls == "CPrgrmPhoneCall":
            return Obj(cls, [self.counted(
                "phone calls",
                lambda: self._object_at(self.pos, {"CPhoneCall"}),
                lambda: self.fixed("CPhoneCall", 8))])
        if cls == "CType99Opts":
            head = self.take(4, "Type 99 options")
            tones = ObjList("Type 99 tones", counted=False)
            for _ in range(3):
                tones.items.append(self.fixed("CT99", 33))
            return Obj(cls, [head, tones])
        if cls in OPTION_DATA_SIZES:
            return Obj(cls, [self.take(OPTION_DATA_SIZES[cls], cls)])
        raise WalkError(f"option {cls} at 0x{start:x} has no known size")

    def _wan_entry(self):
        if self.header({"CP25TrkWan"}) is None:
            return None
        start = self.pos
        self.cstring("WAN name")
        self.take(6, "WAN entry")
        return Obj("CP25TrkWan", [self.d[start:self.pos]])


# ── writer ────────────────────────────────────────────────────────────

class _Writer:
    def __init__(self, schemas):
        self.out = bytearray()
        self.schemas = schemas
        self.class_index = {}
        self.next_index = 1

    def obj(self, o):
        if o is None:
            self.out += struct.pack("<H", NULL_TAG)
            return
        idx = self.class_index.get(o.cls)
        if idx is None:
            schema = self.schemas.get(o.cls, SCHEMAS.get(o.cls))
            if schema is None:
                raise ValueError(f"no schema known for class {o.cls}")
            name = o.cls.encode("ascii")
            self.out += struct.pack("<HHH", NEW_CLASS_TAG, schema, len(name))
            self.out += name
            self.class_index[o.cls] = self.next_index
            self.next_index += 1
        else:
            if idx >= BIG_OBJECT_TAG:
                raise ValueError("archive too large for 16-bit class tags")
            self.out += struct.pack("<H", CLASS_TAG | idx)
        self.next_index += 1
        for part in o.parts:
            if isinstance(part, ObjList):
                self.lst(part)
            else:
                self.out += part

    def lst(self, lst):
        if lst.counted:
            if len(lst.items) > 0xFFFE:
                raise ValueError(f"too many items in {lst.name}")
            self.out += struct.pack("<H", len(lst.items))
        for item in lst.items:
            self.obj(item)


def serialize(doc):
    """Write a :class:`Document` with fresh tags and counts."""
    schemas = dict(SCHEMAS)
    schemas.update(doc.schemas)
    w = _Writer(schemas)
    w.obj(doc.root)
    return bytes(w.out)


# ── public API ────────────────────────────────────────────────────────

def read_cstring(data, pos):
    """Read an MFC CString from ``data`` at ``pos``; return (str, end)."""
    w = _Walker(data, lenient=True)
    w.pos = pos
    raw = w.cstring()
    n = raw[0]
    body = raw[1:] if n != 0xFF else raw[3:]
    return body.decode("latin-1"), w.pos


def write_cstring(text):
    """Encode an MFC CString (1-byte length, or 0xFF + 16-bit length)."""
    raw = text.encode("latin-1", errors="replace")
    if len(raw) < 0xFF:
        return struct.pack("<B", len(raw)) + raw
    if len(raw) < 0xFFFE:
        return b"\xff" + struct.pack("<H", len(raw)) + raw
    return b"\xff\xff\xff" + struct.pack("<I", len(raw)) + raw


def read_document(data, lenient=True):
    """Read PRS bytes into ``(Document, WalkReport)``.

    Raises :class:`WalkError` when the bytes do not follow the known layout.
    """
    w = _Walker(data, lenient)
    try:
        doc = w.document()
    except WalkError:
        raise
    except (IndexError, struct.error, UnicodeDecodeError, ValueError) as e:
        raise WalkError(f"unreadable at 0x{w.pos:x}: {e}") from e
    return doc, w.r


def document_from_prs(prs, lenient=True):
    return read_document(prs.to_bytes(), lenient)[0]


@dataclass
class Problem:
    offset: int
    message: str


def check_bytes(data):
    """List the tags and counts that are wrong (empty when the file is
    consistent).  Raises :class:`WalkError` when the file cannot be read."""
    _, rep = read_document(data, lenient=True)
    problems = []
    for t in rep.tags:
        want = rep.class_index[t.class_name]
        if t.value != want:
            problems.append(Problem(
                t.offset,
                f"{t.class_name} tag holds index {t.value}, should be {want}"))
    for c in rep.counts:
        if c.value != c.items:
            problems.append(Problem(
                c.offset, f"{c.name} count holds {c.value}, list has "
                          f"{c.items}"))
    return problems


def check(prs):
    return check_bytes(prs.to_bytes())


def repair_bytes(data):
    """Return the bytes rewritten with correct tags and counts."""
    doc, _ = read_document(data, lenient=True)
    return serialize(doc)


def repair(prs):
    """Rewrite ``prs`` in place with correct tags and counts.

    Returns True when anything changed.  Raises :class:`WalkError` (and
    changes nothing) when the file cannot be read.
    """
    from .prs_parser import parse_prs_bytes
    before = prs.to_bytes()
    after = repair_bytes(before)
    if after == before:
        return False
    prs.sections = parse_prs_bytes(after, verify=False).sections
    prs.file_size = len(after)
    return True


def write_document(prs, doc):
    """Replace the sections of ``prs`` with the serialized ``doc``."""
    from .prs_parser import parse_prs_bytes
    data = serialize(doc)
    prs.sections = parse_prs_bytes(data, verify=False).sections
    prs.file_size = len(data)


def describe(prs):
    """Human-readable map of the archive (classes, indices, list counts)."""
    _, rep = read_document(prs.to_bytes(), lenient=True)
    lines = [f"Archive: {rep.entries} map entries, "
             f"{len(rep.class_order)} classes"]
    for name in rep.class_order:
        lines.append(f"  [{rep.class_index[name]:5d}] {name}")
    lines.append("Lists:")
    for c in rep.counts:
        if c.name in ("items", "ECC entries", "unknown list"):
            continue
        flag = "" if c.value == c.items else f"  (stored {c.value})"
        lines.append(f"  0x{c.offset:05x} {c.name:16s} {c.items}{flag}")
    return "\n".join(lines)
