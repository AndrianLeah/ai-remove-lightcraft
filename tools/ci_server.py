"""AI Remove's local OpenAI-compatible server (airemove-cli --serve, 2.0 beta) end to end, for the CI runners:
tools/ci_smoke.py remove DIR runs this after ci_reflections.py, with the install's own Python (DIR: an install with LaMa
only).

The server runs here on a free port and is asked what a program using OpenAI's image API asks: the Craft apps' shared
layer (craft-ai-integrations' `craft-ai-openai`, a custom OpenAI-compatible connection) sends `POST /images/edits` as
multipart/form-data with `model`, `prompt`, `image` and `mask` files, and reads `data[0].b64_json`. The picture is a
synthetic one (a red disc on a textured ground), removed with the real LaMa; DAI is a stand-in for engines.DAI (it
"finds" a fifth of the light as a reflection), so the strengths and the optional mask are checked without its weights.

Checks: the models listed (LaMa, and DAI at four strengths); only requests to 127.0.0.1 on its port, none with an
Origin, and the key when there is one; the disc gone with OpenAI's mask (transparent = change) and with a white one,
with and without a prompt, the picture the same size and unchanged away from the removal; a PNG by default, a JPEG or
a WebP (lossless at output_compression 100) when output_format asks; the refusals (no mask, an unknown model, an empty
mask, links instead of b64_json, too many variants, an unknown output_format or compression, another path) in
OpenAI's error shape; DAI
on the whole picture or only where the mask is, more at 100 % than at 50 %, its engine loaded once for every job.
Exit status 1 at the first check that fails.

  ci_server.py DIR
"""
import argparse
import base64
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

import numpy as np
from PIL import Image


class Failed(Exception):
    pass


def expect(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)
    if not ok:
        raise Failed(what)


W, H = 1200, 900
DISC = (450, 400, 70)  # centre x, y and radius of the thing to remove


def scene():
    """A ground with texture (so a fill has something to continue) and a red disc on it."""
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:H, 0:W].astype(np.float64)
    g = 0.35 + 0.25 * x / W + 0.1 * np.sin(y / 23.0) * np.cos(x / 31.0)
    rgb = np.stack([g * 0.9, g * 0.8, g * 0.6], -1) + rng.normal(0, 0.02, (H, W, 3))
    cx, cy, r = DISC
    disc = (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    rgb[disc] = (0.85, 0.08, 0.08)
    return (np.clip(rgb, 0, 1) * 255).round().astype(np.uint8), disc


def png(a, mode=None):
    buf = io.BytesIO()
    Image.fromarray(a, mode).save(buf, format="PNG")
    return buf.getvalue()


def multipart(fields, files):
    """As craft-ai-openai builds /images/edits: text fields, then files with a filename and a media type."""
    b = uuid.uuid4().hex
    out = []
    for name, value in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, data) in files.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                   f"Content-Type: image/png\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return f"multipart/form-data; boundary={b}", b"".join(out)


class Client:
    def __init__(self, port, key=None):
        self.port, self.key = port, key

    def ask(self, method, path, body=None, ctype=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=600)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        if ctype:
            h["Content-Type"] = ctype
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, json.loads(data.decode("utf-8")) if data else None

    def edit(self, model, image, mask=None, prompt=None, **extra):
        fields = {"model": model}
        if prompt is not None:
            fields["prompt"] = prompt
        fields.update({k: str(v) for k, v in extra.items()})
        files = {"image": ("image.png", image)}
        if mask is not None:
            files["mask"] = ("mask.png", mask)
        ctype, body = multipart(fields, files)
        return self.ask("POST", "/v1/images/edits", body, ctype)


def result(reply):
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(reply["data"][0]["b64_json"]))).convert("RGB"))


def run(d, out):
    sys.path.insert(0, str(d / "airemove"))
    os.environ["AIREMOVE_LOG"] = str(out / "server.log")
    import engines
    import server

    made = []

    class StandInDAI:
        """engines.DAI's remove(): the area (floats, sRGB-encoded) with a fifth of its light "found" as a reflection."""

        def __init__(self, log=print):
            made.append(self)

        def remove(self, src, progress=None):
            from rawdng import RawDNG
            return RawDNG.oetf(RawDNG.inv_oetf(src) * 0.8).astype(np.float32), 1.0

        def unload(self):
            pass

    engines.DAI = StandInDAI
    usable = engines.usable
    engines.usable = lambda m, dev=None: True if m == "dai" else usable(m, dev)

    srv = server.make_server(0, log=lambda *a: print("  info", *a, flush=True))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    c = Client(port)

    status, body = c.ask("GET", "/health")
    expect(status == 200 and body.get("ok"), f"listening on 127.0.0.1:{port} ({body})")
    status, body = c.ask("GET", "/v1/models")
    ids = [m["id"] for m in body["data"]] if status == 200 else []
    expect("lama" in ids and {f"dai-{s}" for s in (50, 75, 100, 125)} <= set(ids)
           and set(ids) <= set(server.FILL_MODELS) | {f"dai-{s}" for s in server.DAI_STRENGTHS},
           f"GET /v1/models lists what this computer runs: {ids}")

    # only this computer, no web page, the key when there is one
    status, body = c.ask("GET", "/v1/models", headers={"Host": f"evil.example:{port}"})
    expect(status == 403, f"a request addressed to another host is refused ({status})")
    status, body = c.ask("GET", "/v1/models", headers={"Origin": "https://evil.example"})
    expect(status == 403, f"a browser page is refused ({status})")
    keyed = server.make_server(0, key="s3cret-key", log=lambda *a: None)
    threading.Thread(target=keyed.serve_forever, daemon=True).start()
    kp = keyed.server_address[1]
    expect(Client(kp).ask("GET", "/v1/models")[0] == 401 and Client(kp, "wrong").ask("GET", "/v1/models")[0] == 401
           and Client(kp, "s3cret-key").ask("GET", "/v1/models")[0] == 200,
           "with a key: refused without it or with another, answered with it")
    keyed.shutdown()

    # LaMa: OpenAI's mask (transparent = change), then a white one without a prompt
    pic, disc = scene()
    from scipy import ndimage as ndi
    near = ndi.binary_dilation(disc, iterations=6)
    ring = ndi.binary_dilation(disc, iterations=40) & ~ndi.binary_dilation(disc, iterations=15)
    far = ~ndi.binary_dilation(disc, iterations=260)
    rgba = np.dstack([np.zeros((H, W, 3), np.uint8), np.where(near, 0, 255).astype(np.uint8)])
    for name, mask, prompt in (("OpenAI's mask (transparent = change)", png(rgba, "RGBA"), "remove the red disc"),
                               ("a white mask, no prompt", png(np.where(near, 255, 0).astype(np.uint8), "L"), None)):
        status, body = c.edit("lama", png(pic), mask, prompt)
        expect(status == 200 and len(body.get("data", [])) == 1, f"LaMa with {name}: 200, one result ({status})")
        res = result(body).astype(np.float64)
        o = pic.astype(np.float64)
        before = np.linalg.norm(o[disc].mean(0) - o[ring].mean(0))
        after = np.linalg.norm(res[disc].mean(0) - res[ring].mean(0))
        expect(res.shape == o.shape and after < 0.15 * before,
               f"  the disc is gone: colour distance to the ground {before:.0f} -> {after:.1f}, size {W}x{H} kept")
        expect(np.array_equal(res[far], o[far]), "  away from the removal, every pixel as it was")
    expect(base64.b64decode(body["data"][0]["b64_json"]).startswith(b"\x89PNG\r\n\x1a\n")
           and body.get("output_format") == "png", "  a PNG when no output_format is asked")

    # output_format: a JPEG at output_compression's quality, a WebP lossless at 100 (the default). Away from the
    # removal the JPEG must be what a JPEG of the original at that quality is, pixel for pixel: no loss but its own.
    buf = io.BytesIO()
    Image.fromarray(pic).save(buf, format="JPEG", quality=80)
    jpeg_of_pic = np.asarray(Image.open(buf).convert("RGB"))
    for fmt, extra, magic, ref in (("jpeg", {"output_compression": 80}, b"\xff\xd8\xff", jpeg_of_pic),
                                   ("webp", {}, b"RIFF", pic)):
        status, body = c.edit("lama", png(pic), png(rgba, "RGBA"), output_format=fmt, **extra)
        data = base64.b64decode(body["data"][0]["b64_json"]) if status == 200 else b""
        res = result(body) if status == 200 else None
        o = pic.astype(np.float64)
        ok = (status == 200 and data.startswith(magic) and body.get("output_format") == fmt and res.shape == pic.shape
              and np.linalg.norm(res[disc].astype(np.float64).mean(0) - res[ring].astype(np.float64).mean(0))
              < 0.15 * np.linalg.norm(o[disc].mean(0) - o[ring].mean(0)))
        expect(ok and np.array_equal(res[far], ref[far]),
               f"output_format={fmt} {extra or ''}: a {fmt.upper()} ({len(data) // 1024} KiB), the disc gone, away from "
               f"it {'a JPEG of the original at the same quality' if ref is jpeg_of_pic else 'every pixel as it was'}")

    # refusals, in OpenAI's error shape
    def refused(status, body, want, code=None):
        e = (body or {}).get("error") or {}
        return status == want and e.get("message") and (code is None or e.get("code") == code)
    status, body = c.edit("lama", png(pic))
    expect(refused(status, body, 400, "missing_mask"), f"no mask for LaMa: 400 missing_mask ({status})")
    status, body = c.edit("dall-e-3", png(pic), png(rgba, "RGBA"))
    expect(refused(status, body, 404, "model_not_found"), f"an unknown model: 404 model_not_found ({status})")
    status, body = c.edit("lama", png(pic), png(np.zeros((H, W), np.uint8), "L"))
    expect(refused(status, body, 400, "invalid_mask"), f"a mask that marks nothing: 400 invalid_mask ({status})")
    status, body = c.edit("lama", png(pic), png(rgba, "RGBA"), response_format="url")
    expect(refused(status, body, 400), f"links instead of b64_json: 400 ({status})")
    status, body = c.edit("lama", png(pic), png(rgba, "RGBA"), n=9)
    expect(refused(status, body, 400), f"n=9: 400 ({status})")
    status, body = c.edit("lama", png(pic), png(rgba, "RGBA"), output_format="gif")
    expect(refused(status, body, 400), f"output_format=gif: 400 ({status})")
    status, body = c.edit("lama", png(pic), png(rgba, "RGBA"), output_format="jpeg", output_compression=101)
    expect(refused(status, body, 400), f"output_compression=101: 400 ({status})")
    status, body = c.ask("POST", "/v1/images/generations", b"{}", "application/json")
    expect(refused(status, body, 404), f"text-to-image is not served: 404 ({status})")
    status, body = c.ask("POST", "/v1/images/edits", b"{}", "application/json")
    expect(refused(status, body, 400), f"a body that is not multipart: 400 ({status})")

    # DAI: the whole picture, or only where the mask is; more at 100 % than at 50 %; the engine loaded once
    base = pic.astype(np.float64).mean(-1)
    darker = {}
    for strength in (50, 100):
        status, body = c.edit(f"dai-{strength}", png(pic))
        expect(status == 200, f"dai-{strength} on the whole picture, no mask: 200 ({status})")
        darker[strength] = base.mean() - result(body).astype(np.float64).mean(-1).mean()
    expect(0 < darker[50] < darker[100], f"more is taken at 100 % than at 50 %: {darker[100]:.1f} and "
                                         f"{darker[50]:.1f} levels darker")
    left = np.zeros((H, W), bool)
    left[:, : W // 2] = True
    status, body = c.edit("dai-100", png(pic), png(np.where(left, 255, 0).astype(np.uint8), "L"))
    res = result(body).astype(np.float64).mean(-1) if status == 200 else base
    away = np.zeros((H, W), bool)
    away[:, int(W * 0.75):] = True  # past the fading edge
    expect(status == 200 and (base - res)[:, : W // 4].mean() > 0.5 * darker[100]
           and np.abs(base - res)[away].max() == 0,
           "dai-100 with a mask: the reflection taken away there, the rest untouched")
    expect(len(made) == 1, f"DAI's engine loaded once for {3} jobs ({len(made)})")
    srv.shutdown()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", help="install folder")
    a = ap.parse_args()
    d = Path(a.dir).expanduser().resolve()
    out = Path(tempfile.mkdtemp(prefix="airemove-ci-server-"))
    print(f"server {d}", flush=True)
    try:
        run(d, out)
    except Failed as e:
        print("  FAIL " + str(e), flush=True)
        return 1
    print("  ok   the local OpenAI-compatible server end to end", flush=True)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
