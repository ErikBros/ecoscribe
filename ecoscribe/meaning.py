"""Search the calls by meaning (dictado-2i1), switched on only once a word search came back empty.

The Claude app's search_meetings finds calls by their words (search.py). When a search finds no call,
log_miss() counts it in the transcripts folder (.search-misses.json: how many and the day of the last
one; never the words looked for). From the first logged miss on ([search] meaning = "auto", the
default; "on" and "off" force it), the background app keeps a second index next to the transcripts:
every call cut into overlapping passages of about PASSAGE_WORDS words, each turned into a vector by a
multilingual embedding model on the CPU (onnxruntime and tokenizers, which faster-whisper already
brings: no new dependency). A query is turned into a vector the same way and the calls with the
closest passages come back, so a topic asked in English finds a call held in Swedish, Spanish or
Greek even when none of the words match.

Model: multilingual-e5-large, int8 (about 0.55 GB, MIT license), downloaded once into the models
folder after the first miss. Chosen for accuracy over speed: on an invented four-language set
(30 queries, 20 passages, every query in another language or other words than its passage) it put
the right passage first 28 times, against 26 for e5-base fp32 (1.1 GB, and no faster), 23 for
e5-base int8 (15x faster) and 21 for e5-small. It is slow, which is why it runs in the background
after calls: about 2 to 3 passages a second on half of a 16-thread desktop CPU, so a one-hour call
takes about a minute.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import time
from datetime import date
from pathlib import Path

from . import export, paths, sessions

log = logging.getLogger(__name__)

REPO = "intfloat/multilingual-e5-large"
REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"  # pinned: the files we tested
ONNX = "onnx/model_qint8_avx512_vnni.onnx"
TOKENIZER = "onnx/tokenizer.json"
MODEL_DIR = "intfloat--multilingual-e5-large-int8"
DONE = ".complete"
MAX_TOKENS = 512  # the model's limit; a passage is far shorter
PASSAGE_WORDS = 100  # words in a passage
STEP_WORDS = 75  # a passage starts this many words after the last: a quarter overlaps
BATCH = 8
MISSES = ".search-misses.json"  # inside the transcripts folder: list_sessions only looks at folders
FILE = ".meaning.sqlite"
SCHEMA = 1
MODES = ("auto", "on", "off")


# ---------------- the miss log ----------------
def misses(root: Path) -> int:
    try:
        return int(json.loads((Path(root) / MISSES).read_text(encoding="utf-8")).get("misses") or 0)
    except (OSError, ValueError, AttributeError):
        return 0


def log_miss(root: Path, today: date | None = None) -> int:
    """A word search found no call: count it. Only the count and the day, never what was looked for."""
    n = misses(root) + 1
    try:
        Path(root).mkdir(parents=True, exist_ok=True)
        sessions._write_json(Path(root) / MISSES, {"misses": n, "last": (today or date.today()).isoformat()})
    except OSError:
        log.exception("search miss not logged")
        return n - 1
    log.info("search miss logged (%d so far)", n)
    return n


def switched_on(root: Path, mode: str = "auto") -> bool:
    """[search] meaning: "on" always, "off" never, "auto" once a word search has missed."""
    mode = str(mode or "auto").lower()
    if mode not in MODES:
        log.warning("[search] meaning = %r unknown: auto", mode)
        mode = "auto"
    return mode == "on" or (mode == "auto" and misses(root) > 0)


# ---------------- the model ----------------
def model_dir(models_root: str = "") -> Path:
    return (Path(models_root) if models_root else paths.data_dir() / "models") / MODEL_DIR


def model_ready(models_root: str = "") -> bool:
    d = model_dir(models_root)
    return (d / DONE).exists() and (d / ONNX).is_file() and (d / TOKENIZER).is_file()


def download(models_root: str = "") -> Path:
    """The model's two files as plain files (no cache symlinks), pinned to REVISION. Idempotent."""
    out = model_dir(models_root)
    if model_ready(models_root):
        return out
    from huggingface_hub import snapshot_download
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    log.info("meaning model downloading (%s)", REPO)
    snapshot_download(REPO, revision=REVISION, allow_patterns=[ONNX, TOKENIZER], local_dir=str(tmp))
    (tmp / DONE).write_text(f"{REPO}@{REVISION}", encoding="utf-8")
    shutil.rmtree(out, ignore_errors=True)
    os.replace(tmp, out)
    log.info("meaning model ready in %s", out)
    return out


class Embedder:
    """multilingual-e5: "query: " / "passage: " prefixes, the mean of the last hidden states, unit length."""

    def __init__(self, d: Path):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(str(Path(d) / TOKENIZER))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.enable_padding()
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)  # leave half the CPU to everything else
        self.sess = ort.InferenceSession(str(Path(d) / ONNX), so, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def embed(self, texts: list[str], kind: str = "passage"):
        import numpy as np
        out = []
        for i in range(0, len(texts), BATCH):
            enc = self.tok.encode_batch([f"{kind}: {t}" for t in texts[i:i + BATCH]])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            h = self.sess.run(None, feed)[0]
            v = (h * mask[..., None]).sum(1) / np.maximum(mask.sum(1, keepdims=True), 1)
            out.append(v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12))
        return np.vstack(out).astype(np.float32) if out else np.zeros((0, 0), np.float32)


# ---------------- passages and the index ----------------
def passages(segments: list[dict]) -> list[dict]:
    """The call's words in windows of PASSAGE_WORDS, every STEP_WORDS: each with the time and speaker
    of the turn it starts in."""
    words = [(w, t["t0"], t.get("speaker") or "") for t in export.turns(segments) for w in t["text"].split()]
    out = []
    for at in range(0, len(words), STEP_WORDS):
        chunk = words[at:at + PASSAGE_WORDS]
        out.append({"t0": chunk[0][1], "speaker": chunk[0][2], "text": " ".join(w for w, _, _ in chunk)})
        if at + PASSAGE_WORDS >= len(words):
            break
    return out


class Index:
    """Passages and their vectors in .meaning.sqlite next to the transcripts; only a cache of them."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.db = self.root / FILE
        self.con = self._open()

    def _open(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.db), timeout=5, check_same_thread=False)
        try:
            if con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA:
                return con
        except sqlite3.DatabaseError:
            pass
        con.close()  # Windows can't delete a file that is still open
        log.info("meaning index rebuilt (%s)", self.db)
        for p in (self.db, Path(str(self.db) + "-journal")):
            p.unlink(missing_ok=True)
        con = sqlite3.connect(str(self.db), timeout=5, check_same_thread=False)
        con.executescript(f"""
            CREATE TABLE seen(id TEXT PRIMARY KEY, mtime REAL, model TEXT);
            CREATE TABLE passages(id TEXT, t0 REAL, speaker TEXT, raw TEXT, vec BLOB);
            CREATE INDEX passages_id ON passages(id);
            PRAGMA user_version={SCHEMA};""")
        return con

    def _now(self) -> dict[str, float]:
        now = {}
        for d in (p for p in self.root.iterdir() if p.is_dir()) if self.root.is_dir() else ():
            try:
                now[d.name] = (d / "transcript.json").stat().st_mtime
            except OSError:
                continue
        return now

    def stale(self) -> list[str]:
        """Sessions whose transcript is new or changed since they were indexed (newest first)."""
        seen = {sid: (m, model) for sid, m, model in self.con.execute("SELECT id, mtime, model FROM seen")}
        return sorted((sid for sid, m in self._now().items() if seen.get(sid) != (m, REVISION)), reverse=True)

    def refresh(self, embedder, budget_s: float | None = None, clock=time.monotonic) -> int:
        """Index the stale sessions (and forget deleted ones) until budget_s runs out. Returns how many
        are still stale. `embedder` is an Embedder or a function returning one (loaded only if needed)."""
        now = self._now()
        with self.con:
            for (sid,) in self.con.execute("SELECT id FROM seen").fetchall():
                if sid not in now:
                    self.con.execute("DELETE FROM passages WHERE id = ?", (sid,))
                    self.con.execute("DELETE FROM seen WHERE id = ?", (sid,))
        todo = self.stale()
        start = clock()
        for i, sid in enumerate(todo):
            if budget_s is not None and clock() - start > budget_s:
                return len(todo) - i
            try:
                segs = json.loads((self.root / sid / "transcript.json").read_text(encoding="utf-8"))["segments"]
            except (OSError, ValueError, KeyError):
                continue
            ps = passages(segs)
            if callable(embedder) and not hasattr(embedder, "embed"):
                embedder = embedder()
            vecs = embedder.embed([p["text"] for p in ps]) if ps else []
            with self.con:
                self.con.execute("DELETE FROM passages WHERE id = ?", (sid,))
                self.con.executemany("INSERT INTO passages(id, t0, speaker, raw, vec) VALUES (?, ?, ?, ?, ?)",
                                     [(sid, p["t0"], p["speaker"], p["text"], v.tobytes()) for p, v in zip(ps, vecs)])
                self.con.execute("INSERT OR REPLACE INTO seen(id, mtime, model) VALUES (?, ?, ?)", (sid, now[sid], REVISION))
        return 0

    def search(self, q: str, embedder, limit: int = 5, per_session: int = 3, keep=lambda meta: True) -> list[dict]:
        """Calls whose passages are closest to q, best first: the score is the best passage's
        (cosine, about 0.7 for unrelated text to 0.9 for the same thing said)."""
        import numpy as np
        rows = self.con.execute("SELECT id, t0, speaker, raw, vec FROM passages").fetchall()
        if not rows:
            return []
        if callable(embedder) and not hasattr(embedder, "embed"):
            embedder = embedder()
        qv = embedder.embed([q], kind="query")[0]
        scores = np.frombuffer(b"".join(r[4] for r in rows), dtype=np.float32).reshape(len(rows), -1) @ qv
        groups: dict[str, list] = {}
        for i in np.argsort(-scores):
            groups.setdefault(rows[i][0], []).append((float(scores[i]), rows[i]))
        out = []
        for sid, hits in sorted(groups.items(), key=lambda kv: -kv[1][0][0]):
            try:
                meta = sessions.read_meta(self.root / sid)
            except (OSError, ValueError):
                continue
            if not keep(meta):
                continue
            names = meta.get("speaker_names") or {}
            best = sorted(hits[:per_session], key=lambda h: h[1][1])
            out.append({"id": sid, "title": meta.get("title", ""), "date": export._date(meta),
                        "found_by": "meaning", "score": round(hits[0][0], 3),
                        "hits": [{"at": export._hms(r[1]), "score": round(s, 3),
                                  "speaker": names.get(r[2]) or export._SPEAKER.get(r[2], r[2]) or "", "text": r[3]}
                                 for s, r in best]})
            if len(out) >= max(1, int(limit)):
                break
        return out

    def close(self) -> None:
        self.con.close()


# ---------------- keeping it current in the background ----------------
def main(config_path: str | None = None) -> int:
    """`--meaning-index`: download the model if needed, index the calls not indexed yet, exit."""
    from . import config, winutil
    winutil.setup_logging(paths.data_dir() / "meaning.log", logging.INFO)
    cfg = config.load(Path(config_path) if config_path else paths.config_path())
    root = sessions.root_dir(cfg.transcribe.root)
    if not switched_on(root, cfg.search.meaning):
        log.info("meaning search is off")
        return 0
    try:
        d = download(cfg.transcribe.models_root)
        idx = Index(root)
        try:
            n = len(idx.stale())
            idx.refresh(lambda: Embedder(d))
        finally:
            idx.close()
    except Exception:
        log.exception("meaning index failed")
        return 1
    log.info("meaning index current (%d calls added or changed)", n)
    return 0


EVERY_S = 300


class Sweeper:
    """From the background app's 1 s meetings poll: at most every EVERY_S, while nothing records or
    transcribes and meaning search is switched on, start one `--meaning-index` worker when the model
    is missing or a call is not indexed yet."""

    def __init__(self, cfg, root: Path, spawn, clock=time.time):
        self.cfg, self.root, self.spawn, self.clock = cfg, Path(root), spawn, clock
        self.proc, self._at = None, 0.0

    def tick(self, busy: set | None = None) -> bool:
        if self.proc is not None:
            if self.proc.poll() is None:
                return False
            self.proc = None
        now = self.clock()
        if busy or now - self._at < EVERY_S:
            return False
        self._at = now
        try:
            if not switched_on(self.root, self.cfg.search.meaning):
                return False
            if model_ready(self.cfg.transcribe.models_root) and (self.root / FILE).exists():
                idx = Index(self.root)
                try:
                    if not idx.stale():
                        return False
                finally:
                    idx.close()
            self.proc = self.spawn(["--meaning-index"])
            log.info("meaning index started pid=%s", getattr(self.proc, "pid", None))
            return True
        except Exception:
            log.exception("meaning index not started")
            self.proc = None
            return False
