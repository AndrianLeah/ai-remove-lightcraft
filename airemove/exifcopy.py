"""The original's EXIF in the DNG AI Remove writes. AI Remove's DNG is LightCraft's raw DNG export with the fills
written into its sensor data (rawdng.write_cfa), and LightCraft's DNG writer embeds only an XMP packet (capture
time, rating, creator, its development): the original's EXIF — exposure, aperture, ISO, focal length, lens, serial
numbers, GPS, artist, copyright — was lost. copy_exif() puts it back.

Read from the original:
- a TIFF-based raw (CR2, NEF, ARW, PEF, DNG…): its first IFD's date, artist and copyright, its EXIF and GPS IFDs;
- a Canon CR3: the same from its CMT1 (first IFD), CMT2 (EXIF) and CMT4 (GPS) boxes, each a TIFF stream;
- anything else (Fujifilm RAF…): the EXIF of the JPEG it embeds (an "Exif\\0\\0" TIFF stream).
Written into the DNG without moving a byte of it: the EXIF and GPS IFDs and a new first IFD (the DNG's own entries,
their values where they were, plus the pointers to those IFDs and the date, artist and copyright it lacks) are
appended, and the header points to the new first IFD. Values change byte order when the two files' differ. Left out:
the MakerNote (its offsets point into the original file, and copied elsewhere it would be corrupt) and the
Interoperability IFD; a DNG that has an EXIF IFD already is left as it is. Standard library only.
"""
import struct

SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}  # bytes per value
NUM = {3: "H", 4: "I", 5: "II", 8: "h", 9: "i", 10: "ii", 11: "f", 12: "d", 13: "I"}  # numeric values' layout
EXIF_IFD, GPS_IFD, INTEROP_IFD, MAKER_NOTE = 34665, 34853, 40965, 37500
FIRST_IFD_TAGS = (306, 315, 33432)  # DateTime, Artist, Copyright: the first IFD's, copied when the DNG lacks them
SKIP = {MAKER_NOTE, INTEROP_IFD, EXIF_IFD, GPS_IFD}


class Tiff:
    """A classic TIFF stream (b"II*\\0" or b"MM\\0*") in a bytes object, from offset `base`."""

    def __init__(self, data, base=0):
        self.data, self.base = data, base
        self.order = {b"II": "<", b"MM": ">"}.get(data[base:base + 2])
        if self.order is None or struct.unpack(self.order + "H", data[base + 2:base + 4])[0] != 42:
            raise ValueError("not a classic TIFF stream")

    def u32(self, off):
        return struct.unpack(self.order + "I", self.data[self.base + off:self.base + off + 4])[0]

    def first(self):
        return self.u32(4)

    def ifd(self, off):
        """{tag: (type, count, value bytes in this stream's byte order)} of the IFD at off; unknown types left out."""
        b, o = self.data, self.base + off
        n = struct.unpack(self.order + "H", b[o:o + 2])[0]
        out = {}
        for i in range(n):
            e = o + 2 + 12 * i
            tag, typ, count = struct.unpack(self.order + "HHI", b[e:e + 8])
            if typ not in SIZE or count > 1 << 24:
                continue
            size = SIZE[typ] * count
            start = e + 8 if size <= 4 else self.base + struct.unpack(self.order + "I", b[e + 8:e + 12])[0]
            if start + size > len(b):
                continue
            out[tag] = (typ, count, b[start:start + size])
        return out

    def pointer(self, entries, tag):
        e = entries.get(tag)
        return struct.unpack(self.order + "I", e[2][:4])[0] if e and e[1] >= 1 and len(e[2]) >= 4 else None


def _recode(typ, count, value, src, dst):
    """value (count values of TIFF type typ) from byte order src to dst."""
    if src == dst or typ not in NUM:
        return value
    fmt = NUM[typ] * count
    return struct.pack(dst + fmt, *struct.unpack(src + fmt, value))


def _from_tiff(t):
    """(first IFD's tags, EXIF IFD, GPS IFD) of a TIFF stream, each {tag: (type, count, value)} in t's byte order."""
    first = t.ifd(t.first())
    exif = t.ifd(t.pointer(first, EXIF_IFD)) if t.pointer(first, EXIF_IFD) else {}
    gps = t.ifd(t.pointer(first, GPS_IFD)) if t.pointer(first, GPS_IFD) else {}
    return first, exif, gps


def _boxes(data, start, end):
    """ISO BMFF boxes between start and end: (type, payload start, payload end)."""
    o = start
    while o + 8 <= end:
        size, kind = struct.unpack(">I4s", data[o:o + 8])
        head = 8
        if size == 1:
            size, head = struct.unpack(">Q", data[o + 8:o + 16])[0], 16
        elif size == 0:
            size = end - o
        if size < head:
            return
        yield kind, o + head, min(o + size, end)
        o += size


def read_exif(data):
    """The original's metadata: {"order", "first", "exif", "gps"} (values in that byte order), or None."""
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        t = Tiff(data)
        first, exif, gps = _from_tiff(t)
        return {"order": t.order, "first": first, "exif": exif, "gps": gps} if exif else None
    if data[4:12] == b"ftypcrx ":  # Canon CR3: moov / uuid (Canon's) / CMT1…CMT4
        found = {}

        def walk(start, end, depth=0):
            for kind, a, b in _boxes(data, start, end):
                if kind in (b"CMT1", b"CMT2", b"CMT4"):
                    found[kind] = Tiff(data, a)
                elif kind == b"moov" and depth == 0:
                    walk(a, b, 1)
                elif kind == b"uuid" and depth == 1:
                    walk(a + 16, b, 2)  # after the 16-byte uuid
        walk(0, len(data))
        if b"CMT2" not in found:
            return None
        cmt2 = found[b"CMT2"]
        out = {"order": cmt2.order, "first": {}, "exif": cmt2.ifd(cmt2.first()), "gps": {}}
        for kind, part in ((b"CMT1", "first"), (b"CMT4", "gps")):
            t = found.get(kind)
            if t is not None:
                out[part] = {tag: (typ, n, _recode(typ, n, v, t.order, cmt2.order))
                             for tag, (typ, n, v) in t.ifd(t.first()).items()}
        return out
    at = data.find(b"Exif\x00\x00", 0, 16 << 20)  # an embedded JPEG's APP1 (RAF, and others)
    while at >= 0:
        try:
            t = Tiff(data, at + 6)
            first, exif, gps = _from_tiff(t)
            if exif:
                return {"order": t.order, "first": first, "exif": exif, "gps": gps}
        except (ValueError, struct.error):
            pass
        at = data.find(b"Exif\x00\x00", at + 6, 16 << 20)
    return None


def _ifd_bytes(entries, order, at):
    """An IFD at file offset at (entries: {tag: (type, count, value bytes in order)}, next IFD 0), with its
    out-of-line values after it: its bytes."""
    tags = sorted(entries)
    head = 2 + 12 * len(tags) + 4
    out, extra = [struct.pack(order + "H", len(tags))], b""
    for tag in tags:
        typ, count, value = entries[tag]
        if len(value) <= 4:
            field = value.ljust(4, b"\x00")
        else:
            field = struct.pack(order + "I", at + head + len(extra))
            extra += value + (b"\x00" if len(value) % 2 else b"")
        out.append(struct.pack(order + "HHI", tag, typ, count) + field)
    out.append(struct.pack(order + "I", 0))
    return b"".join(out) + extra


def copy_exif(original, dng):
    """The original's EXIF (and GPS, date, artist, copyright) into dng, appended (see the module). Returns what was
    copied, in words, or why nothing was."""
    with open(original, "rb") as f:
        meta = read_exif(f.read())
    if meta is None:
        return "no EXIF found in the original"
    with open(dng, "rb") as f:
        data = f.read()
    t = Tiff(data)
    first_off = t.first()
    n = struct.unpack(t.order + "H", data[first_off:first_off + 2])[0]
    raw = {}  # the DNG's own first IFD, entries as they are (their out-of-line values stay where they are)
    for i in range(n):
        e = first_off + 2 + 12 * i
        tag, typ, count = struct.unpack(t.order + "HHI", data[e:e + 8])
        raw[tag] = (typ, count, data[e + 8:e + 12])
    if EXIF_IFD in raw:
        return "the DNG has EXIF already: left as it is"
    next_ifd = data[first_off + 2 + 12 * n:first_off + 2 + 12 * n + 4]
    src, dst = meta["order"], t.order

    def convert(entries):
        return {tag: (typ, count, _recode(typ, count, v, src, dst)) for tag, (typ, count, v) in entries.items()
                if tag not in SKIP and typ != 13}

    exif, gps = convert(meta["exif"]), convert(meta["gps"])
    added = {tag: v for tag, v in convert({k: meta["first"][k] for k in FIRST_IFD_TAGS if k in meta["first"]}).items()
             if tag not in raw}
    end = len(data) + len(data) % 2
    blob = b"\x00" * (end - len(data))
    exif_at = end
    blob += _ifd_bytes(exif, dst, exif_at)
    gps_at = None
    if gps:
        blob += b"\x00" * (len(blob) % 2)
        gps_at = end + len(blob)
        blob += _ifd_bytes(gps, dst, gps_at)
    blob += b"\x00" * (len(blob) % 2)
    new_first = end + len(blob)
    # the new first IFD: the DNG's entries unchanged (each one's 4-byte field, inline value or offset, as it was),
    # the pointers to the new IFDs and the tags it lacked added; its link to the next IFD kept
    fields = dict(raw)
    fields[EXIF_IFD] = (4, 1, struct.pack(dst + "I", exif_at))
    if gps_at is not None:
        fields[GPS_IFD] = (4, 1, struct.pack(dst + "I", gps_at))
    tags = sorted(set(fields) | set(added))
    head = 2 + 12 * len(tags) + 4
    out, extra = [struct.pack(dst + "H", len(tags))], b""
    for tag in tags:
        if tag in added:
            typ, count, value = added[tag]
            if len(value) > 4:
                field = struct.pack(dst + "I", new_first + head + len(extra))
                extra += value + (b"\x00" if len(value) % 2 else b"")
            else:
                field = value.ljust(4, b"\x00")
        else:
            typ, count, field = fields[tag]
        out.append(struct.pack(dst + "HHI", tag, typ, count) + field)
    blob += b"".join(out) + next_ifd + extra
    with open(dng, "r+b") as f:
        f.seek(len(data))
        f.write(blob)
        f.seek(4)
        f.write(struct.pack(dst + "I", new_first))
    return (f"{len(exif)} EXIF tags" + (f", GPS ({len(gps)} tags)" if gps else "")
            + (", " + ", ".join({306: "date", 315: "artist", 33432: "copyright"}[k] for k in sorted(added))
               if added else ""))
