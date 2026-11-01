#!/usr/bin/env python3
"""Reader for Game Maker 5.3/5.3a executables (data format version 530).

Usage:  python3 -I gm53_reader.py GAME.exe OUTDIR [--trace]

Written from scratch to recover the lost sources of two 2006 games, Stelo and Pacmanio.
Format knowledge comes from reading (not running) LateralGM's GmFileReader.java
(.gmd 5.3a layout) and the GM4 decompiler notes (seeded swap-table cipher),
plus our own inspection of the executables.

Container layout found in Stelo's exe:
  offset 1500000: u32 1230500 (GM5 exe marker), u32 seed
  offset 1500008..: every byte substituted with inv(table(seed)), where
      table = identity; for i in 1..10000: j = 1 + (i*seed) % 254; swap t[j], t[j+1]
  the decrypted stream contains, a few dozen bytes in, the usual GM project
  header u32 1234321, u32 530, followed by a .gmd-like body.
"""
import os, struct, sys, zlib, json, io

MARK_OFFSET = 1500000
EXE_MAGIC = 1230500
GMD_MAGIC = 1234321


def swap_tables(seed):
    t = list(range(256))
    for i in range(1, 10001):
        j = 1 + ((i * seed) % 254)
        t[j], t[j + 1] = t[j + 1], t[j]
    inv = [0] * 256
    for i in range(256):
        inv[t[i]] = i
    return t, inv


def find_marker(d):
    """Find the GM5 exe marker; normally at 1500000, otherwise scan."""
    if len(d) > MARK_OFFSET + 8 and struct.unpack_from('<I', d, MARK_OFFSET)[0] == EXE_MAGIC:
        return MARK_OFFSET
    p = d.find(struct.pack('<I', EXE_MAGIC))
    if p < 0:
        raise SystemExit('no GM5 exe marker (1230500) found')
    return p


class Reader:
    def __init__(self, dec, raw, base, trace=False):
        self.d = dec        # decrypted bytes (index = file offset - base)
        self.raw = raw      # undecrypted bytes, same indexing
        self.p = 0
        self.base = base
        self.trace = trace

    def i4(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]
        self.p += 4
        return v

    def b(self):
        return self.i4() != 0

    def dbl(self):
        v = struct.unpack_from('<d', self.d, self.p)[0]
        self.p += 8
        return v

    def s(self):
        n = self.i4()
        if n < 0 or n > 10_000_000:
            raise ValueError(f'bad string length {n} at {self.p - 4 + self.base}')
        v = self.d[self.p:self.p + n]
        self.p += n
        return v.decode('cp1252', 'replace')

    def blob(self, n, plain=False):
        src = self.raw if plain else self.d
        v = src[self.p:self.p + n]
        self.p += n
        return bytes(v)

    def zblob(self):
        """length-prefixed zlib block; try decrypted then raw bytes."""
        n = self.i4()
        start = self.p
        for src in (self.d, self.raw):
            try:
                out = zlib.decompress(bytes(src[start:start + n]))
                self.p = start + n
                return out
            except zlib.error:
                pass
        self.p = start + n
        return None

    def log(self, *a):
        if self.trace:
            print(f'[{self.p + self.base}]', *a, file=sys.stderr)


def save_bmp_as_png(bmp, path):
    """Convert a BMP blob to PNG with Pillow if available, else keep .bmp."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(bmp))
        im.save(path + '.png')
        return im
    except Exception:
        open(path + '.bmp', 'wb').write(bmp)
        return None


EVENT_NAMES = ['create', 'destroy', 'alarm', 'step', 'collision', 'keyboard',
               'mouse', 'other', 'draw', 'keypress', 'keyrelease']


def read_actions(r):
    ver = r.i4()
    n = r.i4()
    acts = []
    for _ in range(n):
        a = {}
        r.i4()  # unused
        a['lib'] = r.i4()
        a['id'] = r.i4()
        a['kind'] = r.i4()
        a['may_be_relative'] = r.b()
        a['is_question'] = r.b()
        a['applies_to_something'] = r.b()
        a['exec_type'] = r.i4()
        a['function'] = r.s()
        a['code'] = r.s()
        a['argc'] = r.i4()
        nk = r.i4()
        a['argkinds'] = [r.i4() for _ in range(nk)]
        a['applies_to'] = r.i4()
        a['relative'] = r.b()
        na = r.i4()
        a['args'] = [r.s() for _ in range(na)]
        a['not'] = r.b()
        acts.append(a)
    return acts


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    trace = '--trace' in sys.argv
    exe, out = args[0], args[1]
    d = open(exe, 'rb').read()
    m = find_marker(d)
    seed = struct.unpack_from('<I', d, m + 4)[0]
    _, inv = swap_tables(seed)
    base = m + 8
    raw = d[base:]
    dec = bytes(inv[c] for c in raw)
    hdr = dec.find(struct.pack('<I', GMD_MAGIC))
    r = Reader(dec, raw, base, trace)
    r.p = hdr
    info = {'exe': os.path.basename(exe), 'marker_offset': m, 'seed': seed,
            'pre_header_bytes': dec[:hdr].hex(), 'header_offset': base + hdr}
    assert r.i4() == GMD_MAGIC
    info['format_version'] = r.i4()
    os.makedirs(out, exist_ok=True)
    G = {'info': info}
    try:
        parse(r, G, out)
    except Exception as e:
        import traceback
        G['error'] = f'{type(e).__name__}: {e} at file offset {r.p + base}'
        traceback.print_exc()
    G['info']['stopped_at_offset'] = r.p + base
    G['info']['file_size'] = len(d)
    json.dump(G, open(os.path.join(out, 'project.json'), 'w'), indent=1, ensure_ascii=False, default=str)
    print('done; stopped at', r.p + base, 'of', len(d), 'error:', G.get('error'))


def parse(r, G, out):
    # ---------------- header + settings (ver 530) ----------------
    G['info']['reserved'] = r.i4()
    G['info']['game_id'] = r.i4()
    G['info']['guid'] = r.blob(16).hex()
    st = {}
    st['ver'] = r.i4()
    r.log('settings ver', st['ver'])
    st['fullscreen'] = r.b()
    st['dont_draw_border'] = r.b()
    st['display_cursor'] = r.b()
    st['scaling'] = r.i4()
    st['fullscreen_scale_and_hw'] = [r.i4(), r.i4()]
    st['set_resolution'] = r.b()
    st['color_depth_exclusive'] = [r.i4(), r.i4()]
    st['resolution'] = r.i4()
    st['frequency'] = r.i4()
    st['vblank_caption'] = [r.i4(), r.i4()]
    st['dont_show_buttons'] = r.b()
    st['f4_f1_esc_f5'] = [r.b(), r.b(), r.b(), r.b()]
    st['unknown2'] = [r.i4(), r.i4()]
    st['priority'] = r.i4()
    st['freeze_on_lose_focus'] = r.b()
    st['load_bar'] = r.i4()
    if st['load_bar'] == 2:  # custom
        if r.i4() != -1:
            r.zblob()
        if r.i4() != -1:
            r.zblob()
    st['custom_load_image'] = r.b()
    if st['custom_load_image']:
        if r.i4() != -1:
            img = r.zblob()
            if img:
                save_bmp_as_png(img, os.path.join(out, 'load_image'))
    st['load_image_transparent'] = r.b()
    st['load_image_alpha'] = r.i4()
    st['scale_progress_bar'] = r.b()
    n = r.i4()
    ico = r.blob(n)
    open(os.path.join(out, 'game.ico'), 'wb').write(ico)
    st['display_errors_log_abort'] = [r.b(), r.b(), r.b()]
    st['errors_flags'] = r.i4()
    st['author'] = r.s()
    st['version'] = r.i4()
    st['last_changed'] = r.dbl()
    st['information'] = r.s()
    nc = r.i4()
    st['constants'] = [(r.s(), r.s()) for _ in range(nc)]
    G['settings'] = st
    r.log('settings done', st)
    parse_resources(r, G, out)


def mk(out, *p):
    path = os.path.join(out, *p)
    os.makedirs(path, exist_ok=True)
    return path


def parse_resources(r, G, out):
    # ---------------- sounds ----------------
    ver = r.i4(); n = r.i4(); r.log('sounds', ver, n)
    sounds = G['sounds'] = []
    sd = mk(out, 'sounds')
    for i in range(n):
        if not r.b():
            sounds.append(None); continue
        s = {'id': i, 'name': r.s()}
        s['ver'] = v = r.i4()
        if v == 440:
            s['kind'] = r.i4()
            s['ext'] = r.s()
            if s['kind'] != -1:
                data = r.zblob()
                if data is not None:
                    fn = s['name'] + (s['ext'] or '.bin')
                    open(os.path.join(sd, fn), 'wb').write(data)
                    s['file'] = 'sounds/' + fn
                    s['size'] = len(data)
            s['unknown'] = [r.i4(), r.i4()]
            s['preload'] = not r.b()
        else:
            raise ValueError(f'sound ver {v}')
        r.log('sound', s)
        sounds.append(s)

    # ---------------- sprites ----------------
    ver = r.i4(); n = r.i4(); r.log('sprites', ver, n)
    sprites = G['sprites'] = []
    spd = mk(out, 'sprites')
    for i in range(n):
        if not r.b():
            sprites.append(None); continue
        s = {'id': i, 'name': r.s()}
        s['ver'] = v = r.i4()
        r.log('sprite', s)
        s['w'] = r.i4(); s['h'] = r.i4()
        s['bbox_lrbt'] = [r.i4(), r.i4(), r.i4(), r.i4()]
        s['transparent'] = r.b()
        if v > 400:
            s['smooth'] = r.b(); s['preload'] = r.b()
        s['bbox_mode'] = r.i4()
        s['precise'] = r.b()
        if v == 400:
            s['video_mem'] = r.i4()
            s['preload'] = not r.b()
        s['origin'] = [r.i4(), r.i4()]
        nsub = r.i4()
        s['frames'] = []
        for k in range(nsub):
            if r.i4() == -1:
                continue
            img = r.zblob()
            fn = f"{s['name']}_{k}"
            if img is not None:
                im = save_bmp_as_png(img, os.path.join(spd, fn))
                s['frames'].append('sprites/' + fn + ('.png' if im else '.bmp'))
            else:
                s['frames'].append(None)
        sprites.append(s)

    # ---------------- backgrounds ----------------
    ver = r.i4(); n = r.i4(); r.log('backgrounds', ver, n)
    bgs = G['backgrounds'] = []
    bd = mk(out, 'backgrounds')
    for i in range(n):
        if not r.b():
            bgs.append(None); continue
        s = {'id': i, 'name': r.s()}
        s['ver'] = v = r.i4()
        s['w'] = r.i4(); s['h'] = r.i4()
        s['transparent'] = r.b()
        if v > 400:
            s['smooth'] = r.b(); s['preload'] = r.b(); s['tileset'] = r.b()
            s['tile'] = [r.i4() for _ in range(6)]
        else:
            s['video_mem'] = r.i4(); s['preload'] = not r.b()
        if r.b():
            if r.i4() != -1:
                img = r.zblob()
                if img is not None:
                    im = save_bmp_as_png(img, os.path.join(bd, s['name']))
                    s['file'] = 'backgrounds/' + s['name'] + ('.png' if im else '.bmp')
        r.log('bg', s)
        bgs.append(s)

    # ---------------- paths ----------------
    ver = r.i4(); n = r.i4(); r.log('paths', ver, n)
    paths = G['paths'] = []
    for i in range(n):
        if not r.b():
            paths.append(None); continue
        s = {'id': i, 'name': r.s(), 'ver': r.i4()}
        s['smooth'] = r.b(); s['closed'] = r.b()
        s['precision'] = r.i4(); s['room'] = r.i4(); s['snap'] = [r.i4(), r.i4()]
        s['points'] = [(r.dbl(), r.dbl(), r.dbl()) for _ in range(r.i4())]
        paths.append(s)

    # ---------------- scripts ----------------
    ver = r.i4(); n = r.i4(); r.log('scripts', ver, n)
    scripts = G['scripts'] = []
    scd = mk(out, 'scripts')
    for i in range(n):
        if not r.b():
            scripts.append(None); continue
        s = {'id': i, 'name': r.s(), 'ver': r.i4()}
        code = r.s()
        open(os.path.join(scd, s['name'] + '.gml'), 'w').write(code)
        s['file'] = 'scripts/' + s['name'] + '.gml'
        scripts.append(s)

    # ---------------- data files (5.x) / fonts ----------------
    ver = r.i4(); r.log('datafiles/fonts ver', ver)
    if ver == 440:
        n = r.i4()
        dfs = G['datafiles'] = []
        dd = mk(out, 'datafiles')
        for i in range(n):
            if not r.b():
                dfs.append(None); continue
            s = {'id': i, 'name': r.s(), 'ver': r.i4(), 'filename': r.s()}
            if r.b():
                data = r.zblob()
                if data is not None:
                    fn = os.path.basename(s['filename'].replace('\\', '/')) or s['name']
                    open(os.path.join(dd, fn), 'wb').write(data)
                    s['file'] = 'datafiles/' + fn
            s['export'] = r.i4(); s['overwrite'] = r.b(); s['free'] = r.b(); s['remove'] = r.b()
            r.log('datafile', s)
            dfs.append(s)
    else:
        raise ValueError(f'fonts ver {ver} not handled')

    # ---------------- timelines ----------------
    ver = r.i4(); n = r.i4(); r.log('timelines', ver, n)
    tls = G['timelines'] = []
    for i in range(n):
        if not r.b():
            tls.append(None); continue
        s = {'id': i, 'name': r.s(), 'ver': r.i4(), 'moments': []}
        for _ in range(r.i4()):
            step = r.i4()
            s['moments'].append({'step': step, 'actions': read_actions(r)})
        tls.append(s)

    # ---------------- objects ----------------
    ver = r.i4(); n = r.i4(); r.log('objects', ver, n)
    objs = G['objects'] = []
    for i in range(n):
        if not r.b():
            objs.append(None); continue
        s = {'id': i, 'name': r.s(), 'ver': r.i4()}
        s['sprite'] = r.i4(); s['solid'] = r.b(); s['visible'] = r.b()
        s['depth'] = r.i4(); s['persistent'] = r.b(); s['parent'] = r.i4(); s['mask'] = r.i4()
        r.log('object', s)
        nev = r.i4() + 1
        s['events'] = []
        for j in range(nev):
            while True:
                first = r.i4()
                if first == -1:
                    break
                s['events'].append({'type': EVENT_NAMES[j] if j < len(EVENT_NAMES) else j,
                                    'sub': first, 'actions': read_actions(r)})
        objs.append(s)

    # ---------------- rooms ----------------
    ver = r.i4(); n = r.i4(); r.log('rooms', ver, n)
    rooms = G['rooms'] = []
    for i in range(n):
        if not r.b():
            rooms.append(None); continue
        s = {'id': i, 'name': r.s(), 'ver': r.i4()}
        v2 = s['ver']
        s['caption'] = r.s()
        s['w'] = r.i4(); s['h'] = r.i4(); s['snap_y'] = r.i4(); s['snap_x'] = r.i4()
        s['isometric'] = r.b(); s['speed'] = r.i4(); s['persistent'] = r.b()
        s['bg_color'] = r.i4(); s['draw_bg_color'] = r.i4()
        s['creation_code'] = r.s()
        r.log('room', s)
        s['backgrounds'] = []
        for _ in range(r.i4()):
            s['backgrounds'].append({'visible': r.b(), 'foreground': r.b(), 'bg': r.i4(),
                                     'x': r.i4(), 'y': r.i4(), 'tile_h': r.b(), 'tile_v': r.b(),
                                     'hspeed': r.i4(), 'vspeed': r.i4(), 'stretch': r.b()})
        s['views_enabled'] = r.b()
        s['views'] = []
        for _ in range(r.i4()):
            vw = {'visible': r.b(), 'view': [r.i4() for _ in range(4)], 'port_xy': [r.i4(), r.i4()]}
            if v2 > 520:
                vw['port_wh'] = [r.i4(), r.i4()]
            vw['border_hv_speed_hv'] = [r.i4() for _ in range(4)]
            vw['follow'] = r.i4()
            s['views'].append(vw)
        s['instances'] = []
        for _ in range(r.i4()):
            x = r.i4(); y = r.i4(); o = r.i4(); iid = r.i4(); code = r.s()
            locked = r.b()
            s['instances'].append({'x': x, 'y': y, 'obj': o, 'id': iid, 'code': code})
        s['tiles'] = []
        for _ in range(r.i4()):
            t = {'x': r.i4(), 'y': r.i4(), 'bg': r.i4(), 'src': [r.i4(), r.i4()],
                 'size': [r.i4(), r.i4()], 'depth': r.i4(), 'id': r.i4()}
            r.b()
            s['tiles'].append(t)
        s['editor'] = [r.b(), r.i4(), r.i4()] + [r.b() for _ in range(8)]
        if v2 == 520:
            s['editor_tile'] = [r.i4() for _ in range(6)]
        s['editor_tab_scroll'] = [r.i4(), r.i4(), r.i4()]
        rooms.append(s)

    G['last_instance_id'] = r.i4()
    G['last_tile_id'] = r.i4()

    # ---------------- game information ----------------
    ver = r.i4(); r.log('gameinfo ver', ver)
    gi = {'ver': ver, 'bg_color': r.i4(), 'embed': r.b()}
    if ver > 430:
        gi['caption'] = r.s(); gi['rect'] = [r.i4() for _ in range(4)]
        gi['flags'] = [r.b() for _ in range(4)]
    gi['text_rtf'] = r.s()
    open(os.path.join(out, 'game_information.rtf'), 'w').write(gi['text_rtf'])
    G['game_information'] = gi

    # ---------------- library init code / room order ----------------
    ver = r.i4(); n = r.i4()
    G['library_init'] = [r.s() for _ in range(n)]
    ver = r.i4(); n = r.i4()
    G['room_order'] = [r.i4() for _ in range(n)]
    r.log('room order', G['room_order'])


if __name__ == '__main__':
    main()
