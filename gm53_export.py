#!/usr/bin/env python3
"""Turn project.json (from gm53_reader.py) into readable source files.

Usage:  python3 -I gm53_export.py OUTDIR      (the same OUTDIR given to the reader)

Writes:
  objects/<name>.gml     every event as readable pseudo-GML (drag&drop actions
                         rendered as function calls, code actions verbatim)
  timelines/<name>.gml
  rooms/<name>.json      instances with object names
  rooms/<name>.png       room rendered with the original sprites (1:1)
  rooms/<name>.txt       ASCII grid (32px cells) for level-design reading
  sprites_contact.png    all sprite frames
  README.md is written by hand, not by this script.
"""
import json, os, sys
from PIL import Image, ImageDraw

EV = {'create': 'Create', 'destroy': 'Destroy', 'alarm': 'Alarm', 'step': 'Step',
      'collision': 'Collision', 'keyboard': 'Keyboard', 'mouse': 'Mouse', 'other': 'Other',
      'draw': 'Draw', 'keypress': 'KeyPress', 'keyrelease': 'KeyRelease'}
STEP_SUB = {0: 'normal', 1: 'begin', 2: 'end'}
OTHER_SUB = {0: 'outside room', 1: 'intersect boundary', 2: 'game start', 3: 'game end',
             4: 'room start', 5: 'room end', 6: 'no more lives', 7: 'animation end',
             8: 'end of path', 9: 'no more health'}
for i in range(10, 26):
    OTHER_SUB[i] = f'user defined {i - 10}'
MOUSE_SUB = {0: 'left button', 1: 'right button', 2: 'middle button', 3: 'no button',
             4: 'left pressed', 5: 'right pressed', 6: 'middle pressed', 7: 'left released',
             8: 'right released', 9: 'middle released', 10: 'mouse enter', 11: 'mouse leave'}
VK = {1: 'any key', 0: 'no key', 8: 'backspace', 13: 'enter', 16: 'shift', 17: 'ctrl', 27: 'escape',
      32: 'space', 37: 'left', 38: 'up', 39: 'right', 40: 'down', 112: 'F1', 113: 'F2'}
# argument kinds (GM action library): resource references are stored as ids
ARG_RES = {5: 'sprites', 6: 'sounds', 7: 'backgrounds', 8: 'paths', 9: 'scripts',
           10: 'objects', 11: 'rooms', 14: 'timelines'}


def load(out):
    return json.load(open(os.path.join(out, 'project.json')))


def name_of(G, kind, i):
    try:
        i = int(i)
    except (TypeError, ValueError):
        return i
    if i < 0:
        if kind != 'objects':
            return 'none'
        return {-1: 'self', -2: 'other', -3: 'all', -4: 'noone', -100: 'none'}.get(i, str(i))
    lst = G.get(kind) or []
    if i < len(lst) and lst[i]:
        return lst[i]['name']
    return f'<{kind[:-1]} {i}>'


def ev_label(G, e):
    t, s = e['type'], e['sub']
    if t == 'collision':
        return f"Collision with {name_of(G, 'objects', s)}"
    if t == 'step':
        return f"Step ({STEP_SUB.get(s, s)})"
    if t == 'alarm':
        return f"Alarm {s}"
    if t == 'other':
        return f"Other: {OTHER_SUB.get(s, s)}"
    if t == 'mouse':
        return f"Mouse: {MOUSE_SUB.get(s, s)}"
    if t in ('keyboard', 'keypress', 'keyrelease'):
        k = VK.get(s, chr(s) if 48 <= s <= 90 else s)
        return f"{EV[t]} <{k}>"
    return f"{EV.get(t, t)} {s if s else ''}".strip()


def render_actions(G, acts):
    lines, ind = [], 0
    pad = lambda: '    ' * ind
    for a in acts:
        k = a['kind']
        args = a['args'][:a['argc']]
        kinds = a['argkinds'][:a['argc']]
        wrap = ''
        if a['applies_to'] != -1:
            wrap = f"with ({name_of(G, 'objects', a['applies_to'])}) "
        if k == 1:
            lines.append(pad() + '{'); ind += 1; continue
        if k == 2:
            ind = max(0, ind - 1); lines.append(pad() + '}'); continue
        if k == 3:
            lines.append(pad() + 'else'); continue
        if k == 4:
            lines.append(pad() + 'exit;'); continue
        if k == 5:
            lines.append(pad() + f'repeat ({args[0] if args else "?"})'); continue
        if k == 6:
            op = '+=' if a['relative'] else '='
            lines.append(pad() + f"{wrap}{args[0]} {op} {args[1]};"); continue
        if k == 7:
            code = args[0] if args else ''
            head = f"{wrap}// --- code action ---" if wrap else '// --- code action ---'
            lines.append(pad() + head)
            for ln in code.replace('\r\n', '\n').split('\n'):
                lines.append(pad() + ln)
            lines.append(pad() + '// --- end code ---')
            continue
        if a['id'] == 605:
            lines.append(pad() + f"// {args[0] if args else ''}"); continue
        shown = []
        for v, kd in zip(args, kinds):
            if kd in ARG_RES:
                shown.append(str(name_of(G, ARG_RES[kd], v)))
            elif kd in (1, 2) and not (v.startswith('"') or v.startswith("'")):
                shown.append(repr(v) if kd == 1 else v)
            else:
                shown.append(v)
        fn = a['function'] or f"action_{a['lib']}_{a['id']}"
        call = f"{fn}({', '.join(shown)})"
        if a['relative']:
            call += '  /*relative*/'
        if a['is_question']:
            call = ('!' if a['not'] else '') + call
            lines.append(pad() + f"{wrap}if {call}")
        else:
            lines.append(pad() + f"{wrap}{call};")
    return lines


def export_objects(G, out):
    od = os.path.join(out, 'objects'); os.makedirs(od, exist_ok=True)
    for o in G['objects']:
        if not o:
            continue
        L = [f"// object {o['name']} (id {o['id']})",
             f"// sprite={name_of(G, 'sprites', o['sprite'])} solid={o['solid']} visible={o['visible']} "
             f"depth={o['depth']} persistent={o['persistent']} parent={name_of(G, 'objects', o['parent'])} "
             f"mask={name_of(G, 'sprites', o['mask'])}", '']
        for e in o['events']:
            L.append(f"#event {ev_label(G, e)}")
            L += render_actions(G, e['actions'])
            L.append('')
        open(os.path.join(od, o['name'] + '.gml'), 'w').write('\n'.join(L))
    td = os.path.join(out, 'timelines'); os.makedirs(td, exist_ok=True)
    for t in G['timelines']:
        if not t:
            continue
        L = [f"// timeline {t['name']} (id {t['id']})", '']
        for m in t['moments']:
            L.append(f"#moment {m['step']}")
            L += render_actions(G, m['actions'])
            L.append('')
        open(os.path.join(td, t['name'] + '.gml'), 'w').write('\n'.join(L))


def gm_color(c):
    return (c & 255, (c >> 8) & 255, (c >> 16) & 255)


def sprite_img(G, out, sid, cache):
    if sid in cache:
        return cache[sid]
    im = None
    if 0 <= sid < len(G['sprites']) and G['sprites'][sid] and G['sprites'][sid]['frames']:
        s = G['sprites'][sid]
        f = s['frames'][0]
        if f:
            im = Image.open(os.path.join(out, f)).convert('RGBA')
            if s.get('transparent'):
                px = im.load(); key = px[0, im.height - 1]  # GM: bottom-left pixel is transparent colour
                data = [(0, 0, 0, 0) if p[:3] == key[:3] else p for p in (im.get_flattened_data() if hasattr(im, 'get_flattened_data') else im.getdata())]
                im.putdata(data)
    cache[sid] = im
    return im


def export_rooms(G, out):
    rd = os.path.join(out, 'rooms'); os.makedirs(rd, exist_ok=True)
    cache = {}
    order = G.get('room_order', [])
    for r in G['rooms']:
        if not r:
            continue
        insts = [{'x': i['x'], 'y': i['y'], 'object': name_of(G, 'objects', i['obj']),
                  **({'creation_code': i['code']} if i['code'] else {})} for i in r['instances']]
        meta = {k: r[k] for k in ('id', 'name', 'caption', 'w', 'h', 'speed', 'snap_x', 'snap_y',
                                  'persistent', 'bg_color', 'creation_code', 'views_enabled')}
        meta['order_position'] = order.index(r['id']) if r['id'] in order else None
        meta['backgrounds'] = [dict(b, bg_name=name_of(G, 'backgrounds', b['bg'])) for b in r['backgrounds'] if b['visible']]
        meta['views'] = [v for v in r['views'] if v['visible']]
        meta['instances'] = insts
        json.dump(meta, open(os.path.join(rd, r['name'] + '.json'), 'w'), indent=1, ensure_ascii=False)
        # render
        im = Image.new('RGBA', (r['w'], r['h']), gm_color(r['bg_color']) + (255,))
        for b in meta['backgrounds']:
            bg = G['backgrounds'][b['bg']] if 0 <= b['bg'] < len(G['backgrounds']) else None
            if bg and bg.get('file'):
                bim = Image.open(os.path.join(out, bg['file'])).convert('RGBA')
                xs = range(b['x'] % bim.width - bim.width, r['w'], bim.width) if b['tile_h'] else [b['x']]
                ys = range(b['y'] % bim.height - bim.height, r['h'], bim.height) if b['tile_v'] else [b['y']]
                for x in xs:
                    for y in ys:
                        im.alpha_composite(bim, (max(x, 0), max(y, 0)), (max(-x, 0), max(-y, 0)))
        objs = G['objects']
        # draw lower depth last (GM draws high depth first)
        for i in sorted(r['instances'], key=lambda i: -(objs[i['obj']]['depth'] if 0 <= i['obj'] < len(objs) and objs[i['obj']] else 0)):
            o = objs[i['obj']] if 0 <= i['obj'] < len(objs) else None
            if not o:
                continue
            spr = o['sprite']
            sim = sprite_img(G, out, spr, cache)
            if sim is None:
                d = ImageDraw.Draw(im)
                d.rectangle([i['x'], i['y'], i['x'] + 31, i['y'] + 31], outline=(255, 0, 255, 255))
                d.text((i['x'] + 2, i['y'] + 2), o['name'][:6], fill=(255, 0, 255, 255))
                continue
            ox, oy = G['sprites'][spr]['origin']
            x, y = i['x'] - ox, i['y'] - oy
            if x < r['w'] and y < r['h'] and x + sim.width > 0 and y + sim.height > 0:
                tmp = Image.new('RGBA', im.size, (0, 0, 0, 0)); tmp.paste(sim, (x, y)); im.alpha_composite(tmp)
        im.convert('RGB').save(os.path.join(rd, r['name'] + '.png'))
        # ASCII grid
        sym = {}
        letters = iter('acdgijklnpqrsuvwyz123456789')
        gw, gh = (r['w'] + 31) // 32, (r['h'] + 31) // 32
        grid = [['.'] * gw for _ in range(gh)]
        for i in r['instances']:
            n = name_of(G, 'objects', i['obj'])
            if n not in sym:
                sym[n] = {'block': '#', 'character': '@', 'ladder': 'H', 'monster': 'M', 'flyer': 'F',
                          'death': 'X', 'levelexit': 'E', 'stelo_poentoj': 'o', 'bonus': 'B',
                          'marker': '|', 'transirejo': 'T', 'b_monster': 'b'}.get(n) or next(letters)
            gx, gy = i['x'] // 32, i['y'] // 32
            if 0 <= gx < gw and 0 <= gy < gh:
                grid[gy][gx] = sym[n]
        legend = '  '.join(f"{v}={k}" for k, v in sym.items())
        txt = f"{r['name']}  {r['w']}x{r['h']}  ({gw}x{gh} cells of 32px)\nlegend: {legend}\n\n" + \
              '\n'.join(''.join(row) for row in grid) + '\n'
        open(os.path.join(rd, r['name'] + '.txt'), 'w').write(txt)


def contact(G, out):
    frames = [(s['name'], f) for s in G['sprites'] if s for f in s['frames'] if f]
    ims = [(n, Image.open(os.path.join(out, f)).convert('RGBA')) for n, f in frames]
    W = 900; x = y = 10; rowh = 0; pos = []
    for n, im in ims:
        w = max(im.width, 110)
        if x + w > W:
            x = 10; y += rowh + 24; rowh = 0
        pos.append((x, y, n, im)); x += w + 10; rowh = max(rowh, im.height)
    sheet = Image.new('RGBA', (W, y + rowh + 30), (70, 70, 80, 255)); d = ImageDraw.Draw(sheet)
    for x, y, n, im in pos:
        sheet.alpha_composite(im, (x, y)); d.text((x, y + im.height + 2), n[:18], fill=(255, 255, 255, 255))
    sheet.save(os.path.join(out, 'sprites_contact.png'))


if __name__ == '__main__':
    out = sys.argv[1]
    G = load(out)
    export_objects(G, out)
    export_rooms(G, out)
    contact(G, out)
    print('exported to', out)
