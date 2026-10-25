"""AI Remove as a local image server that speaks a small part of OpenAI's image API (2.0 beta), so that any program
able to use an "OpenAI-compatible" server can run AI Remove's models: the Craft apps' shared AI layer
(storytold/craft-ai-integrations: a custom OpenAI-compatible connection in Set up AI, declared as image inpainting or
image editing), or anything else.

  airemove-cli --serve [--port 7990] [--key-file PATH]

- `GET /v1/models`: the models this computer can run: lama, rorem, flux, qwen (inpainting: a picture and a mask) and
  dai-50, dai-75, dai-100, dai-125 (reflections in glass, at that strength; the mask is optional).
- `POST /v1/images/edits` (multipart/form-data, as OpenAI's): `model`, `image` (or `image[]`, the first one), `mask`,
  `prompt`, `n`, `output_format` (png, the default; jpeg; webp) and `output_compression` (0-100, the quality of a JPEG
  or WebP; 100, the default, is a lossless WebP). The answer is `{"created": …, "output_format": …, "data":
  [{"b64_json": …}]}`: the whole picture, the same size, unchanged outside the removal (but for a JPEG's or a lossy
  WebP's own loss). A JPEG or WebP keeps a full-size photo under a client's cap on a reply's image: the Craft layer's
  is 32 MiB, which a PNG passes at about 30 megapixels. The work is AI Remove's own: the picture opened on its own (Session, as the window
  does), its removal planned, filled in squares when it is long, blended into the picture.
- `GET /health`: `{"ok": true, "version": …}`.

The mask: OpenAI's convention when it has transparency (transparent = the area to change), else white = the area
(the Craft layer's selection masks are white where selected). The prompt is what FLUX Fill puts there; LaMa and RORem
take none, and Qwen-Image names what it removes by itself (its words are a name, not a description of the fill).

Only this computer can reach it: it listens on 127.0.0.1, answers only requests addressed to that host and port (a
web page cannot use it through DNS rebinding) and none that carry an Origin (a browser), and with --key-file it wants
`Authorization: Bearer <the file's key>` (the key never goes on a command line). One job runs at a time, on the
graphics card; the others wait their turn. The models stay loaded between jobs."""
import base64
import hmac
import io
import json
import shutil
import threading
import time
import uuid
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

import airemove as A
import engines
import system

PORT = 7990  # beside the Craft apps' control ports (7979-7989)
FILL_MODELS = ("lama", "rorem", "flux", "qwen")  # what AI Remove's menu offers for a hole
DAI_STRENGTHS = (50, 75, 100, 125)  # dai-75: 75 % of the reflection's light taken away (the window's default)
MAX_BODY = 256 * 1024 * 1024  # a request's bytes
MAX_PIXELS = 100_000_000  # a picture's
MAX_N = 4  # variants in one request
OUTPUT_FORMATS = ("png", "jpeg", "webp")  # OpenAI's output_format values


class Bad(Exception):
    """A request refused: (HTTP status, message, OpenAI error type, code)."""

    def __init__(self, status, message, kind="invalid_request_error", code=None):
        super().__init__(message)
        self.status, self.kind, self.code = status, kind, code


def available():
    """The model ids this computer can run, in the menu's order (engines.usable: installed, and a graphics card for
    FLUX and Qwen-Image)."""
    dev = engines.device()
    ids = [m for m in FILL_MODELS if m == "lama" or engines.usable(m, dev)]
    if engines.usable("dai", dev):
        ids += [f"dai-{s}" for s in DAI_STRENGTHS]
    return ids


def parse_multipart(body, content_type):
    """multipart/form-data -> {name: [(filename or None, bytes)]}, in the order sent."""
    marker = "boundary="
    if "multipart/form-data" not in content_type.lower() or marker not in content_type:
        raise Bad(400, "the request must be multipart/form-data, as OpenAI's /images/edits")
    boundary = content_type.split(marker, 1)[1].split(";", 1)[0].strip().strip('"').encode("latin-1")
    fields = {}
    for part in body.split(b"--" + boundary)[1:]:
        if part.startswith(b"--"):  # the closing delimiter
            break
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        disposition = next((line for line in head.decode("utf-8", "replace").split("\r\n")
                            if line.lower().startswith("content-disposition:")), "")
        params = {}
        for item in disposition.split(";")[1:]:
            key, eq, value = item.strip().partition("=")
            if eq:
                params[key.lower()] = value.strip().strip('"')
        if "name" in params:
            fields.setdefault(params["name"], []).append((params.get("filename"), data))
    return fields


def text_field(fields, name, default=""):
    values = fields.get(name)
    return values[0][1].decode("utf-8", "replace").strip() if values else default


def open_picture(data):
    """The picture sent, as AI Remove reads pictures: upright (EXIF orientation applied), 8-bit RGB or RGBA."""
    try:
        im = Image.open(io.BytesIO(data))
        if im.width * im.height > MAX_PIXELS:
            raise Bad(413, f"the picture has more than {MAX_PIXELS // 1_000_000} million pixels")
        im = ImageOps.exif_transpose(im)
        im.load()
    except Bad:
        raise
    except Exception:
        raise Bad(400, "the image is not a picture this server can read (PNG, JPEG or WebP)")
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        return im.convert("RGBA")
    if im.mode in ("I;16", "I;16B", "I", "F"):  # 16-bit grey: to 8 bits
        a = np.asarray(im, np.float64)
        im = Image.fromarray(np.clip(a / max(1.0, a.max()) * 255, 0, 255).round().astype(np.uint8))
    return im.convert("RGB")


def read_mask(data, size):
    """The area to change, a boolean array of `size` (width, height): where the mask is transparent when it has
    transparency (OpenAI's convention), else where it is white."""
    try:
        m = Image.open(io.BytesIO(data))
        m.load()
    except Exception:
        raise Bad(400, "the mask is not a picture this server can read (PNG)", code="invalid_mask")
    if m.mode in ("RGBA", "LA", "PA") or (m.mode == "P" and "transparency" in m.info):
        alpha = np.asarray(m.convert("RGBA").getchannel("A"))
        area = alpha < 128 if alpha.min() < 255 else None
    else:
        area = None
    if area is None:
        area = np.asarray(m.convert("L")) > 127
    if area.shape[::-1] != tuple(size):
        area = np.asarray(Image.fromarray(area.astype(np.uint8) * 255).resize(size, Image.NEAREST)) > 127
    if not area.any():
        raise Bad(400, "the mask marks nothing to change", code="invalid_mask")
    return area


def encode(im, fmt, quality):
    """A result's bytes as output_format asks: PNG; JPEG at `quality` (without transparency, which JPEG has not); WebP at
    `quality`, lossless at 100. The colour profile goes along."""
    buf = io.BytesIO()
    icc = im.info.get("icc_profile")
    if fmt == "jpeg":
        im.convert("RGB").save(buf, format="JPEG", quality=quality, icc_profile=icc)
    elif fmt == "webp":
        im.save(buf, format="WEBP", quality=quality, lossless=quality == 100, icc_profile=icc)
    else:
        im.save(buf, format="PNG", icc_profile=icc)
    return buf.getvalue()


class Worker:
    """The jobs, one at a time, with the engines kept loaded from one job to the next (a Session per job: the
    picture's own, as when the window opens it)."""

    def __init__(self, log=print):
        self.lock = threading.Lock()
        self.engines = {}  # Session attribute (engines' ENGINE_ATTRS) -> the engine loaded in it
        self.log = log
        self.models = available()

    def run(self, model, image, mask_data, prompt, n, fmt="png", quality=100):
        """The bytes of `n` results for one request, encoded as `fmt` (see encode)."""
        if model not in self.models:
            raise Bad(404, f"model '{model}' is not available here (GET /v1/models lists them)",
                      code="model_not_found")
        reflection = model.startswith("dai-")
        if mask_data is None and not reflection:
            raise Bad(400, f"'{model}' needs a mask: the area to change", code="missing_mask")
        if reflection or model == "lama":
            n = 1  # one result: DAI's strength is the model id, LaMa always gives the same fill
        with self.lock:
            return self._run(model, image, mask_data, prompt, n, reflection, fmt, quality)

    def _run(self, model, image, mask_data, prompt, n, reflection, fmt, quality):
        job = system.ROOT / "work" / "server" / uuid.uuid4().hex[:12]
        job.mkdir(parents=True)
        s = None
        t0 = time.time()
        try:
            path = job / "picture.png"
            image.save(path, compress_level=1)
            args = Namespace(id=None, raw=str(path), variants=None, auto=None, shadow=False, check=False, app=None)
            s = A.Session(None, args, path)
            s.prepare()
            for attr, eng in self.engines.items():  # the engines loaded by the jobs before
                setattr(s, attr, eng)
            area = (read_mask(mask_data, image.size) if mask_data is not None
                    else np.ones(image.size[::-1], bool))
            sel = np.asarray(Image.fromarray(area.astype(np.uint8) * 255).resize(s.base.size, Image.NEAREST)) > 127
            if not sel.any():
                raise Bad(400, "the mask marks an area too small to change", code="invalid_mask")
            r = s.new_removal(sel, reflection=reflection)
            if model == "lama":
                s.run_lama(r)
            elif reflection:  # its strength first: the log of the run says it
                s.set_strength(r, int(model.split("-", 1)[1]) / 100)
                s.run_model(r, "dai", "")
            else:
                for __ in range(n):  # Qwen-Image names what it removes itself: the prompt is FLUX's
                    s.run_model(r, model, prompt if model == "flux" else "")
            out = []
            for i in range(len(r.candidates)):
                r.chosen, r.user_picked = i, True
                written, __, __ = s.write_all()
                with Image.open(written) as im:
                    out.append(encode(im, fmt, quality))
            self.log(f"server: {model}, {image.width}x{image.height}, {len(out)} result(s) in "
                     f"{time.time() - t0:.1f}s")
            return out
        finally:
            if s is not None:
                self.engines = {attr: getattr(s, attr) for attr in A.ENGINE_ATTRS.values()
                                if getattr(s, attr, None) is not None}
                work = getattr(s, "work", None)
                s.close()
                if work is not None:
                    shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(job, ignore_errors=True)


def make_handler(worker, port, key):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"AI-Remove/{system.VERSION}"
        timeout = 120  # seconds to send a request

        def log_message(self, fmt, *a):  # requests are logged by the worker, not on stderr
            pass

        def reply(self, status, body):
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        def refuse(self, e):
            self.reply(e.status, {"error": {"message": str(e), "type": e.kind, "param": None, "code": e.code}})

        def check(self):
            """Only this computer, no browser page, and the key when there is one."""
            host = (self.headers.get("Host") or "").strip().lower()
            if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                raise Bad(403, "this server answers only requests addressed to it on this computer")
            if self.headers.get("Origin"):
                raise Bad(403, "this server does not answer web pages")
            if key:
                got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
                if not hmac.compare_digest(got.encode("utf-8"), key.encode("utf-8")):
                    raise Bad(401, "a valid key is needed (Authorization: Bearer …)", kind="authentication_error",
                              code="invalid_api_key")

        def do_GET(self):
            try:
                self.check()
                path = self.path.split("?", 1)[0].rstrip("/")
                if path in ("/v1/models", "/models"):
                    self.reply(200, {"object": "list", "data": [
                        {"id": m, "object": "model", "created": 0, "owned_by": "ai-remove"} for m in worker.models]})
                elif path == "/health":
                    self.reply(200, {"ok": True, "version": system.VERSION})
                else:
                    raise Bad(404, f"no such path: {path}")
            except Bad as e:
                self.refuse(e)

        def do_POST(self):
            try:
                self.check()
                path = self.path.split("?", 1)[0].rstrip("/")
                if path not in ("/v1/images/edits", "/images/edits"):
                    raise Bad(404, f"this server only edits images (POST /v1/images/edits), not {path}")
                try:
                    size = int(self.headers.get("Content-Length") or "")
                except ValueError:
                    raise Bad(411, "the request needs a Content-Length")
                if size > MAX_BODY:
                    raise Bad(413, f"the request is over {MAX_BODY // 2 ** 20} MiB")
                fields = parse_multipart(self.rfile.read(size), self.headers.get("Content-Type") or "")
                model = text_field(fields, "model")
                if not model:
                    raise Bad(400, "a model is needed (GET /v1/models lists them)")
                if text_field(fields, "response_format", "b64_json") != "b64_json":
                    raise Bad(400, "only b64_json results are given (no links: nothing leaves this computer)")
                images = fields.get("image") or fields.get("image[]")
                if not images:
                    raise Bad(400, "an image is needed")
                try:
                    n = int(text_field(fields, "n", "1"))
                except ValueError:
                    raise Bad(400, "n must be a whole number")
                if not 1 <= n <= MAX_N:
                    raise Bad(400, f"n must be between 1 and {MAX_N}")
                fmt = text_field(fields, "output_format", "png").lower()
                fmt = "jpeg" if fmt == "jpg" else fmt
                if fmt not in OUTPUT_FORMATS:
                    raise Bad(400, f"output_format must be one of {', '.join(OUTPUT_FORMATS)}")
                try:
                    quality = int(text_field(fields, "output_compression", "100"))
                except ValueError:
                    raise Bad(400, "output_compression must be a whole number")
                if not 0 <= quality <= 100:
                    raise Bad(400, "output_compression must be between 0 and 100")
                mask = fields.get("mask")
                results = worker.run(model, open_picture(images[0][1]), mask[0][1] if mask else None,
                                     text_field(fields, "prompt"), n, fmt, quality)
                self.reply(200, {"created": int(time.time()), "output_format": fmt, "data": [
                    {"b64_json": base64.b64encode(data).decode("ascii")} for data in results]})
            except Bad as e:
                self.refuse(e)
            except A.Stopped:
                self.refuse(Bad(500, "the job was stopped", kind="server_error"))
            except Exception as e:
                A.log("server ERROR:", repr(e))
                self.refuse(Bad(500, f"the removal failed: {e}", kind="server_error"))

    return Handler


def make_server(port=PORT, key=None, log=print):
    """The server, bound to 127.0.0.1:`port` (0: any free port), not yet serving."""
    worker = Worker(log)
    server = ThreadingHTTPServer(("127.0.0.1", port), None)
    server.daemon_threads = True
    server.RequestHandlerClass = make_handler(worker, server.server_address[1], key)
    server.worker = worker
    return server


def serve(args):
    """airemove-cli --serve: one JSON line once it listens, then serves until it is stopped (Ctrl+C)."""
    key = None
    if args.key_file:
        try:
            key = Path(args.key_file).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise A.Fail(f"the key file cannot be read: {e}")
        if not key:
            raise A.Fail("the key file is empty")
    try:
        server = make_server(args.port, key, log=A.log)
    except OSError as e:
        raise A.Fail(f"cannot listen on 127.0.0.1:{args.port}: {e}")
    port = server.server_address[1]
    print(json.dumps({"ok": True, "serving": f"http://127.0.0.1:{port}/v1", "models": server.worker.models,
                      "key": bool(key), "version": system.VERSION}), flush=True)
    A.log(f"server: listening on 127.0.0.1:{port}, models {', '.join(server.worker.models)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
