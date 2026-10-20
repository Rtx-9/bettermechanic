"""Background threads: thumbnail/preview loading, metadata saving, copying."""
from __future__ import annotations

import collections
import os
import queue
import threading
import time
import traceback

from PySide6.QtCore import QObject, Signal

from . import core, develop, imaging
from . import metadata as M


class Bus(QObject):
    """Signals emitted from worker threads, delivered on the UI thread."""
    thumb_ready = Signal(object)                 # item
    meta_ready = Signal(object)                  # item
    preview_ready = Signal(object, bool, object)  # item, full, (w, h, rgb bytes) | None
    saved = Signal(object, str)                  # item, error ('' = ok)
    dev_rendered = Signal(object, str, str, int, int, object)   # item, tag, signature, w, h, rgb bytes
    copy_progress = Signal(dict)
    copy_done = Signal(dict)


class Loader:
    """A small pool of threads with priorities.

    Urgent jobs (the preview you are looking at) go first; otherwise threads
    ask `feeder()` for the next thumbnail, which prefers what is on screen.
    File reading and Pillow decoding release the GIL, so this scales across cores.
    """

    def __init__(self, bus: Bus, settings, n=None):
        self.bus, self.settings = bus, settings
        self.cv = threading.Condition()
        self.urgent = collections.deque()
        self.prefetch = collections.deque()
        self.visible = []          # items, set by the UI thread
        self.order = []            # all items in view order
        self.bg = 0
        self.thumb_size = 256
        self.generation = 0
        self.stopped = False
        n = n or max(2, min(8, (os.cpu_count() or 4) - 1))
        self.threads = [threading.Thread(target=self._run, daemon=True, name=f'loader-{i}') for i in range(n)]
        for t in self.threads:
            t.start()

    # ---- UI-thread API
    def set_items(self, order):
        with self.cv:
            self.order, self.bg, self.visible = list(order), 0, []
            self.urgent.clear()
            self.prefetch.clear()
            self.generation += 1
            self.cv.notify_all()

    def set_visible(self, items, thumb_size):
        with self.cv:
            self.visible, self.thumb_size = list(items), thumb_size
            self.cv.notify_all()

    def rethumb(self, item):
        """Re-render an existing thumbnail after its develop settings changed."""
        with self.cv:
            self.prefetch.appendleft(('rethumb', item, False, None))
            self.cv.notify()

    def preview(self, item, full, box, urgent=True):
        with self.cv:
            (self.urgent if urgent else self.prefetch).append(('preview', item, full, box))
            self.cv.notify()

    def wake(self):
        with self.cv:
            self.cv.notify_all()

    def stop(self):
        """Finish quietly when the window closes."""
        with self.cv:
            self.stopped = True
            self.order, self.visible = [], []
            self.urgent.clear()
            self.prefetch.clear()
            self.cv.notify_all()

    def _emit(self, signal, *args):
        if self.stopped:
            return
        try:
            signal.emit(*args)
        except RuntimeError:        # window already gone
            pass

    # ---- worker side
    def _next(self):
        if self.urgent:
            return self.urgent.popleft()
        if self.prefetch:
            return self.prefetch.popleft()
        hq = self.settings.get('thumb_hq', True)
        for it in self.visible:
            if it.tstate == 0 and not it.tbusy:
                it.tbusy = True
                return ('thumb', it, False, None)
        if hq:
            for it in self.visible:
                if it.tstate == 1 and not it.tbusy:
                    it.tbusy = True
                    return ('thumb', it, True, None)
        while self.bg < len(self.order):
            it = self.order[self.bg]
            if it.tstate == 0 and not it.tbusy:
                it.tbusy = True
                return ('thumb', it, False, None)
            self.bg += 1
        return None

    def _run(self):
        while True:
            with self.cv:
                job = None if self.stopped else self._next()
                while job is None:
                    if self.stopped:
                        return
                    self.cv.wait()
                    job = self._next()
                size = self.thumb_size
            kind, item, flag, box = job
            try:
                if kind == 'thumb':
                    self._thumb(item, flag, size)
                elif kind == 'rethumb':
                    self._rethumb(item)
                else:
                    self._preview(item, flag, box)
            except Exception:
                traceback.print_exc()
                item.tbusy = False

    def _analysis(self, item):
        if item.analysis is None:
            core.ensure_meta(item, self.settings)
            if not item.meta_loaded:
                return None
            self._emit(self.bus.meta_ready, item)
        if item.analysis is None:          # file vanished / unreadable
            from .previews import analyze
            a = analyze(item.pv.path)
            core.absorb(item, a)
        return item.analysis

    def _thumb(self, item, hq, size):
        try:
            a = self._analysis(item)
            box = size if hq else 240
            data, q = imaging.make_thumb(item.pv.path, a, box, hq) if a else (None, 0)
        except OSError:
            data, q = None, 0
        if data:
            item.thumb_base, item.tq = data, q
            dev = dict(item.develop)
            if develop.is_active(dev):
                try:
                    data = imaging.apply_to_jpeg(data, dev)
                except (OSError, ValueError):
                    pass
            item.thumb = data
            item.tstate = 2 if (hq or q >= size * 0.9) else 1
        else:
            item.tstate = 2 if hq and item.thumb else -1
        item.tbusy = False
        if not item.meta_loaded:
            core.ensure_meta(item, self.settings)
            self._emit(self.bus.meta_ready, item)
        self._emit(self.bus.thumb_ready, item)

    def _rethumb(self, item):
        if item.thumb_base:
            try:
                item.thumb = imaging.apply_to_jpeg(item.thumb_base, dict(item.develop))
            except (OSError, ValueError):
                return
            self._emit(self.bus.thumb_ready, item)

    def _preview(self, item, full, box):
        try:
            a = self._analysis(item)
            im = imaging.make_preview(item.pv.path, a, *(box or (0, 0))) if a else None
            img = (im.size[0], im.size[1], im.tobytes()) if im is not None else None
        except OSError:
            img = None
        self._emit(self.bus.preview_ready, item, full, img)


class DevRenderer:
    """Renders develop settings for the large preview on its own thread; newest request per tag wins."""
    ORDER = ('proxy', 'fit', 'full')

    def __init__(self, bus):
        self.bus, self.cv, self.jobs, self.stopped = bus, threading.Condition(), {}, False
        threading.Thread(target=self._run, daemon=True, name='develop').start()

    def request(self, tag, job):
        with self.cv:
            self.jobs[tag] = job
            self.cv.notify()

    def stop(self):
        with self.cv:
            self.stopped = True
            self.jobs.clear()
            self.cv.notify_all()

    def _run(self):
        import numpy as np
        from PIL import Image
        while True:
            with self.cv:
                while not self.jobs and not self.stopped:
                    self.cv.wait()
                if self.stopped:
                    return
                tag = next(t for t in self.ORDER if t in self.jobs)
                item, _, sig, settings, base, proxy_edge = self.jobs.pop(tag)
            try:
                w, h, data = base
                arr = np.frombuffer(data, np.uint8).reshape(h, w, 3)
                if proxy_edge and max(w, h) > proxy_edge:
                    s = proxy_edge / max(w, h)
                    arr = np.asarray(Image.fromarray(arr).resize((round(w * s), round(h * s)), Image.BILINEAR))
                out = develop.render(arr, settings)
                self.bus.dev_rendered.emit(item, tag, sig, out.shape[1], out.shape[0], out.tobytes())
            except RuntimeError:            # window closed
                return
            except Exception:
                traceback.print_exc()


class Saver:
    """Writes metadata snapshots one at a time on its own thread."""

    def __init__(self, bus: Bus, settings):
        self.bus, self.settings = bus, settings
        self.q = queue.Queue()
        self.pending = 0
        threading.Thread(target=self._run, daemon=True, name='saver').start()

    def put(self, item):
        self.pending += 1
        self.q.put((item, M.copy_meta(item.meta), core.develop_edits(item)))

    def _run(self):
        while True:
            item, meta, dev = self.q.get()
            err = ''
            try:
                core.write_item_meta(item, meta, dict(self.settings), dev)
            except Exception as e:      # report and keep going
                err = f'{type(e).__name__}: {e}'
            self.pending -= 1
            try:
                self.bus.saved.emit(item, err)
            except RuntimeError:        # window already gone
                pass


# --------------------------------------------------------------------- copy

PICKERS = {
    'all': lambda it, sel: True,
    'not_rejected': lambda it, sel: it.meta['rating'] != -1,
    'tagged': lambda it, sel: it.meta['tagged'],
    'rated': lambda it, sel: it.meta['rating'] >= 1,
    'people': lambda it, sel: bool(it.meta['people']),
    'selected': lambda it, sel: it.id in sel,
}


class CopyJob(threading.Thread):
    """Ingest / export: copy picked photos with renaming + metadata."""

    CHUNK = 4 << 20

    def __init__(self, bus, items, selected_ids, opts, settings, meta_preset, tag_preset_name, history_path=None):
        super().__init__(daemon=True, name='copy')
        self.history_path = history_path
        self.bus, self.items, self.sel = bus, items, set(selected_ids)
        self.o, self.settings = dict(opts), dict(settings)
        self.preset, self.tag_name = meta_preset, tag_preset_name
        self.cancelled = False
        self.bytes = 0

    def cancel(self):
        self.cancelled = True

    def run(self):
        o, st = self.o, self.settings
        res = {'copied': 0, 'skipped': 0, 'failed': 0, 'errors': [], 'dirs': [], 'seq': st.get('seq', 1),
               'cancelled': False}
        try:
            self.bus.copy_progress.emit({'phase': 'Reading metadata…', 'i': 0, 'n': len(self.items)})
            for it in self.items:
                core.ensure_meta(it, st)
            pick = PICKERS.get(o['which'], PICKERS['all'])
            todo = [it for it in self.items if pick(it, self.sel)]
            total = sum(it.size for it in todo) * (2 if o.get('use_backup') and o.get('backup') else 1)
            roots = [o['dest']] + ([o['backup']] if o.get('use_backup') and o.get('backup') else [])
            seq, t0, dirs = st.get('seq', 1), time.time(), []
            use_hist = o.get('ingest') and o.get('skip_ingested', True)
            hist = core.load_history(self.history_path) if o.get('ingest') else set()
            if use_hist:
                before = len(todo)
                todo = [it for it in todo if core.history_key(it) not in hist]
                res['skipped'] += before - len(todo)
            for k, it in enumerate(todo):
                if self.cancelled:
                    res['cancelled'] = True
                    break
                meta = M.copy_meta(it.meta)
                if self.preset:
                    core.apply_meta_preset(meta, self.preset, it, o.get('preset_mode', 'replace'), self.tag_name)
                sub = core.sanitize_path(core.expand(o['sub'], it, meta, seq, st.get('seq_digits', 4), self.tag_name))
                base = core.sanitize(core.expand(o['rename'], it, meta, seq, st.get('seq_digits', 4), self.tag_name)) or it.base
                self.bus.copy_progress.emit({'phase': 'Copying', 'i': k, 'n': len(todo), 'name': it.name,
                                             'bytes': self.bytes, 'total': total, 't0': t0})
                try:
                    did = False
                    for root in roots:
                        d = os.path.join(root, *sub.split('/')) if sub else root
                        os.makedirs(d, exist_ok=True)
                        if root == o['dest'] and d not in dirs:
                            dirs.append(d)
                        did = self._copy_item(it, meta, d, base) or did
                    if did:
                        res['copied'] += 1
                        seq += 1
                        hist.add(core.history_key(it))
                    else:
                        res['skipped'] += 1
                except Exception as e:
                    if self.cancelled:
                        res['cancelled'] = True
                        break
                    res['failed'] += 1
                    res['errors'].append(f'{it.name}: {e}')
            res['seq'], res['dirs'], res['n'] = seq, dirs, len(todo)
            if o.get('ingest'):
                core.save_history(hist, self.history_path)
        except Exception as e:
            res['errors'].append(f'{type(e).__name__}: {e}')
        self.bus.copy_done.emit(res)

    # ---- helpers
    def _names(self, d, names):
        policy = self.o.get('exists', 'skip')
        if not any(os.path.exists(os.path.join(d, n)) for n in names) or policy == 'overwrite':
            return names
        if policy == 'skip':
            return None
        for i in range(1, 10000):
            cand = [f'{os.path.splitext(n)[0]}-{i}{os.path.splitext(n)[1]}' for n in names]
            if not any(os.path.exists(os.path.join(d, n)) for n in cand):
                return cand
        return None

    def _write(self, path, data: bytes):
        tmp = path + '.bmpart'
        with open(tmp, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, path)
        self.bytes += len(data)

    def _stream(self, src, path):
        tmp = path + '.bmpart'
        try:
            with open(src, 'rb') as fi, open(tmp, 'wb') as fo:
                while True:
                    if self.cancelled:
                        raise InterruptedError('cancelled')
                    b = fi.read(self.CHUNK)
                    if not b:
                        break
                    fo.write(b)
                    self.bytes += len(b)
            st = os.stat(src)
            os.utime(tmp, (st.st_atime, st.st_mtime))
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def _copy_item(self, it, meta, d, base):
        o, st = self.o, self.settings
        p2k, iim = st.get('people_to_keywords', True), st.get('write_iim', True)
        write_meta = o.get('write_meta', True)
        if o.get('fmt') == 'jpeg':
            names = self._names(d, [base + '.jpg'])
            if not names:
                return False
            a = it.analysis
            if a is None:
                from .previews import analyze
                a = analyze(it.pv.path)
            data = imaging.render_jpeg(it.pv.path, a, int(o.get('long_edge') or 0), int(o.get('quality') or 90),
                                       dict(it.develop) if o.get('apply_edits', True) else None)
            if write_meta:
                data = M.rewrite_jpeg(data, meta, p2k, iim)
            self._write(os.path.join(d, names[0]), data)
            return True
        names = self._names(d, [base + '.' + f.ext for f in it.files])
        if not names:
            return False
        embed = st.get('jpeg_mode', 'embed') == 'embed'
        dev = core.develop_edits(it) or None
        for f, n in zip(it.files, names):
            target = os.path.join(d, n)
            if f.kind == 'jpeg' and write_meta and embed:
                with open(f.path, 'rb') as fh:
                    self._write(target, M.rewrite_jpeg(fh.read(), meta, p2k, iim, dev))
            else:
                self._stream(f.path, target)
        need_sidecar = any(f.kind != 'jpeg' or not embed for f in it.files)
        if need_sidecar and (write_meta or it.sidecar):
            existing = None
            if it.sidecar:
                try:
                    with open(it.sidecar, 'r', encoding='utf-8', errors='replace') as fh:
                        existing = fh.read()
                except OSError:
                    pass
            text = M.build_xmp(meta, existing, p2k, dev) if write_meta else existing
            self._write(os.path.join(d, os.path.splitext(names[0])[0] + '.xmp'), text.encode('utf-8'))
        return True
