#!/usr/bin/env python3
"""Minimal VRML 1.0 -> VRML97 converter.

Handles the node set used by typical CAD exports of the era:
Separator, Group, WWWAnchor, Material, Coordinate3, IndexedFaceSet,
IndexedLineSet, Cube, Sphere, Cone, Cylinder, Translation, Rotation,
Scale, Transform, MatrixTransform (skipped), ShapeHints, Info, DEF/USE.

VRML 1.0 is a state machine: Material / Coordinate3 / transforms affect the
nodes that follow them inside the same Separator. This converter replays that
state and emits explicit VRML97 Shape / Transform nodes.

Usage:  python3 vrml1to2.py in.wrl out.wrl
"""
import re, sys

TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}\[\],]|[^\s{}\[\],"]+')


class Node:
    def __init__(self, ntype, defname=None):
        self.type, self.defname = ntype, defname
        self.fields = {}      # name -> list of tokens
        self.children = []    # Node or ('USE', name)


def parse(text):
    text = re.sub(r'#[^\n]*', '', text)
    toks = [t for t in TOKEN.findall(text) if t != ',']
    pos = 0

    def node(defname=None):
        nonlocal pos
        ntype = toks[pos]; pos += 1
        assert toks[pos] == '{', f'expected {{ after {ntype}, got {toks[pos]}'
        pos += 1
        n = Node(ntype, defname)
        while toks[pos] != '}':
            t = toks[pos]
            if t == 'DEF':
                name = toks[pos + 1]; pos += 2
                n.children.append(node(name))
            elif t == 'USE':
                n.children.append(('USE', toks[pos + 1])); pos += 2
            elif pos + 1 < len(toks) and toks[pos + 1] == '{':
                n.children.append(node())
            else:                      # field
                fname = t; pos += 1
                vals = []
                if toks[pos] == '[':
                    pos += 1
                    while toks[pos] != ']':
                        vals.append(toks[pos]); pos += 1
                    pos += 1
                else:
                    # values run until '}', DEF/USE, a child node (Name {) or the next field name
                    while True:
                        t2 = toks[pos]
                        if t2 in ('}', 'DEF', 'USE'):
                            break
                        if pos + 1 < len(toks) and toks[pos + 1] == '{':
                            break
                        if vals and re.match(r'^[a-z][A-Za-z0-9_]*$', t2):
                            break
                        vals.append(t2); pos += 1
                n.fields[fname] = vals
        pos += 1
        return n

    roots = []
    while pos < len(toks):
        if toks[pos] == 'DEF':
            name = toks[pos + 1]; pos += 2; roots.append(node(name))
        else:
            roots.append(node())
    return roots


def fmt(vals, per):
    out = []
    for i in range(0, len(vals), per):
        out.append(' '.join(vals[i:i + per]))
    return out


class Converter:
    def __init__(self):
        self.defs = {}
        self.coord_ids = {}
        self.lines = []
        self.ncoord = 0

    def emit(self, depth, s):
        self.lines.append('  ' * depth + s)

    def material_vrml(self, m):
        if m is None:
            return 'Material { }'
        parts = []
        for f, n in (('diffuseColor', 3), ('ambientColor', 3), ('specularColor', 3),
                     ('emissiveColor', 3), ('shininess', 1), ('transparency', 1)):
            v = m.fields.get(f)
            if v and len(v) >= n:
                vv = v[:n]
                if f == 'ambientColor':   # VRML97 has ambientIntensity instead
                    try:
                        a = sum(float(x) for x in vv) / 3
                        parts.append(f'ambientIntensity {min(max(a / 0.8, 0), 1):.3g}')
                    except ValueError:
                        pass
                    continue
                parts.append(f'{f} {" ".join(vv)}')
        return 'Material { ' + ' '.join(parts) + ' }'

    def coord_vrml(self, c):
        key = id(c)
        if key in self.coord_ids:
            return f'USE {self.coord_ids[key]}'
        self.ncoord += 1
        name = f'C{self.ncoord}'
        self.coord_ids[key] = name
        pts = c.fields.get('point', [])
        body = ',\n'.join('        ' + p for p in fmt(pts, 3))
        return f'DEF {name} Coordinate {{ point [\n{body}\n      ] }}'

    def shape(self, depth, geom, st):
        e = self.emit
        e(depth, 'Shape {')
        e(depth + 1, f'appearance Appearance {{ material {self.material_vrml(st["mat"])} }}')
        e(depth + 1, geom)
        e(depth, '}')

    def ifs(self, n, st, lines=False):
        idx = n.fields.get('coordIndex', [])
        idx_s = ' '.join(idx)
        coord = self.coord_vrml(st['coord']) if st['coord'] else 'Coordinate { }'
        if lines:
            return f'geometry IndexedLineSet {{\n      coord {coord}\n      coordIndex [ {idx_s} ]\n    }}'
        crease = st['crease']
        return (f'geometry IndexedFaceSet {{\n      coord {coord}\n      coordIndex [ {idx_s} ]\n'
                f'      solid {st["solid"]}\n      ccw {st["ccw"]}\n      creaseAngle {crease}\n    }}')

    def group(self, depth, children, st, wrapper_open=None):
        """Emit children of a Separator-like node, replaying VRML1 state."""
        e = self.emit
        opened = 0
        for ch in children:
            if isinstance(ch, tuple):           # USE
                ch = self.defs.get(ch[1])
                if ch is None:
                    continue
            elif ch.defname:
                self.defs[ch.defname] = ch
            t = ch.type
            f = ch.fields
            if t == 'Material':
                st['mat'] = ch
            elif t == 'Coordinate3':
                st['coord'] = ch
            elif t == 'ShapeHints':
                vo = (f.get('vertexOrdering') or ['UNKNOWN_ORDERING'])[0]
                stype = (f.get('shapeType') or ['UNKNOWN_SHAPE_TYPE'])[0]
                st['ccw'] = 'FALSE' if vo == 'CLOCKWISE' else 'TRUE'
                st['solid'] = 'TRUE' if (stype == 'SOLID' and vo != 'UNKNOWN_ORDERING') else 'FALSE'
                if f.get('creaseAngle'):
                    st['crease'] = f['creaseAngle'][0]
            elif t in ('Translation', 'Rotation', 'Scale', 'Transform'):
                if t == 'Translation':
                    fld = f'translation {" ".join(f.get("translation", ["0", "0", "0"]))}'
                elif t == 'Rotation':
                    fld = f'rotation {" ".join(f.get("rotation", ["0", "0", "1", "0"]))}'
                elif t == 'Scale':
                    fld = f'scale {" ".join(f.get("scaleFactor", ["1", "1", "1"]))}'
                else:
                    parts = []
                    for a, b in (('translation', 'translation'), ('rotation', 'rotation'),
                                 ('scaleFactor', 'scale'), ('scaleOrientation', 'scaleOrientation'),
                                 ('center', 'center')):
                        if f.get(a):
                            parts.append(f'{b} {" ".join(f[a])}')
                    fld = ' '.join(parts)
                e(depth, f'Transform {{ {fld} children [')
                depth += 1; opened += 1
            elif t in ('Separator', 'Group', 'TransformSeparator', 'Switch'):
                if t == 'Switch':
                    w = int((f.get('whichChild') or ['-1'])[0])
                    kids = ch.children if w == -3 else (
                        [ch.children[w]] if 0 <= w < len(ch.children) else [])
                else:
                    kids = ch.children
                if t == 'Separator':
                    e(depth, 'Group { children [')
                    self.group(depth + 1, kids, dict(st))
                    e(depth, '] }')
                else:                           # Group: state leaks out
                    self.group(depth, kids, st)
            elif t == 'WWWAnchor':
                url = (f.get('name') or ['""'])[0]
                desc = (f.get('description') or ['""'])[0]
                e(depth, f'Anchor {{ url {url} description {desc} parameter "target=_blank" children [')
                self.group(depth + 1, ch.children, dict(st))
                e(depth, '] }')
            elif t == 'IndexedFaceSet':
                self.shape(depth, self.ifs(ch, st), st)
            elif t == 'IndexedLineSet':
                self.shape(depth, self.ifs(ch, st, lines=True), st)
            elif t == 'Cube':
                w = (f.get('width') or ['2'])[0]; h = (f.get('height') or ['2'])[0]; d = (f.get('depth') or ['2'])[0]
                self.shape(depth, f'geometry Box {{ size {w} {h} {d} }}', st)
            elif t == 'Sphere':
                self.shape(depth, f'geometry Sphere {{ radius {(f.get("radius") or ["1"])[0]} }}', st)
            elif t == 'Cone':
                self.shape(depth, f'geometry Cone {{ bottomRadius {(f.get("bottomRadius") or ["1"])[0]} height {(f.get("height") or ["2"])[0]} }}', st)
            elif t == 'Cylinder':
                self.shape(depth, f'geometry Cylinder {{ radius {(f.get("radius") or ["1"])[0]} height {(f.get("height") or ["2"])[0]} }}', st)
            # Info, normals, bindings etc. are ignored
        for _ in range(opened):
            depth -= 1
            e(depth, '] }')

    def convert(self, roots):
        self.emit(0, '#VRML V2.0 utf8')
        self.emit(0, '# Converted from VRML 1.0')
        self.emit(0, 'NavigationInfo { type [ "EXAMINE", "ANY" ] headlight TRUE }')
        st = {'mat': None, 'coord': None, 'solid': 'FALSE', 'ccw': 'TRUE', 'crease': '0.5'}
        self.group(0, roots, st)
        return '\n'.join(self.lines) + '\n'


def main():
    src, dst = sys.argv[1], sys.argv[2]
    roots = parse(open(src, encoding='latin-1').read())
    out = Converter().convert(roots)
    open(dst, 'w').write(out)
    print(f'wrote {dst}: {len(out)} bytes')


if __name__ == '__main__':
    main()
