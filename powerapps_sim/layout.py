"""Server-side dimensions and line packing for automatic containers."""
from __future__ import annotations


def bounded(value, minimum, maximum):
    return max(minimum, min(value, maximum)) if maximum > 0 else max(minimum, value)


def portions(available, children):
    """Distribute a zero-basis flex line, freezing children at their limits.

    Each entry is (path, weight, fixed size, minimum, maximum). Fixed controls
    never shrink. When minimums exceed the line, the container overflows.
    """
    sizes, pending = {}, {}
    for path, weight, fixed, minimum, maximum in children:
        if weight > 0:
            pending[path] = (weight, minimum, maximum)
        else:
            sizes[path] = bounded(fixed, minimum, maximum)
    remaining = available - sum(sizes.values())
    while pending:
        total = sum(v[0] for v in pending.values())
        proposed = {p: remaining * v[0] / total for p, v in pending.items()}
        clamped = {p: bounded(proposed[p], v[1], v[2]) for p, v in pending.items()}
        violation = sum(clamped[p] - proposed[p] for p in pending)
        if abs(violation) < 1e-8:
            sizes.update(clamped)
            break
        # CSS freezes minimum violations while growing, maximum violations
        # while shrinking. Freezing both at once misallocates mixed limits.
        frozen = [p for p in pending if (clamped[p] > proposed[p] if violation > 0 else clamped[p] < proposed[p])]
        for path in frozen:
            sizes[path] = clamped[path]
            remaining -= sizes[path]
            del pending[path]
    return {path: sizes[path] for path, *_ in children}


def inset(ref, dimension):
    if ref.family in ('Text', 'FluentV8/Label'):
        from .canvas_text import inset as native_inset
        return native_inset(ref, dimension)
    # Native shapes have no padding members. Their layout box has zero inset;
    # do not expose unrelated COMMON defaults as public Power Fx properties.
    if ref.family in ('Rectangle','Circle','Star'):
        return (0,0)
    names = ("PaddingLeft", "PaddingRight") if dimension == "Width" else ("PaddingTop", "PaddingBottom")
    # Blank numeric decoration contributes no inset; retain Blank in the
    # public property value rather than inventing an authored default.
    border = max(0, ref.property("BorderThickness") or 0)
    return tuple(max(0, ref.property(n) or 0) + border for n in names)


def limits(ref, dimension):
    minimum = max(0, ref.property("LayoutMin" + dimension), sum(inset(ref, dimension)))
    maximum = max(0, ref.property("LayoutMax" + dimension))
    return minimum, maximum


def alignment(ref):
    own = ref.property("AlignInContainer")
    return ref.parent.property("LayoutAlignItems") if own == "SetByContainer" else own


def main_sizes(parent):
    runtime = parent.runtime
    key = parent.path
    if key in runtime.layout_cache:
        return runtime.layout_cache[key]
    axis = "Width" if parent.property("LayoutDirection") == "Horizontal" else "Height"
    children = []
    for child in parent.children:
        if not child.property("Visible"):
            continue
        minimum, maximum = limits(child, axis)
        weight = max(0, child.property("FillPortions"))
        fixed = 0 if weight else child.intrinsic_dimension(axis)
        children.append((child.path, weight, fixed, minimum, maximum))
    gap = max(0, parent.property("LayoutGap"))
    space = parent.property(axis) - sum(inset(parent, axis)) - gap * max(0, len(children) - 1) if any(c[1] > 0 for c in children) else 0
    sizes = portions(space, children)
    runtime.layout_cache[key] = sizes
    return sizes


def dimension(ref, name):
    parent = ref.parent
    axis = "Width" if parent.property("LayoutDirection") == "Horizontal" else "Height"
    minimum, maximum = limits(ref, name)
    if name == axis:
        sizes = main_sizes(parent)
        return sizes[ref.path] if ref.path in sizes else bounded(ref.intrinsic_dimension(name), minimum, maximum)
    # Intrinsic measurement precedes stretch when an auto-sized parent uses a
    # child's authored size. Otherwise Parent.Height -> Child.Height -> parent
    # creates a false formula cycle for a valid content-sized container.
    measuring_parent = (parent.path, name) in ref.runtime.evaluating or (parent.path, name) in ref.runtime.intrinsic_measuring
    value = parent.property(name) - sum(inset(parent, name)) if alignment(ref) == "Stretch" and not measuring_parent else ref.intrinsic_dimension(name)
    return bounded(value, minimum, maximum)


def position(ref, name):
    parent = ref.parent
    horizontal = parent.property("LayoutDirection") == "Horizontal"
    axis = "Width" if horizontal else "Height"
    target_dimension = "Width" if name == "X" else "Height"
    start, end = inset(parent, target_dimension)
    if target_dimension != axis:
        free = parent.property(target_dimension) - start - end - ref.property(target_dimension)
        return start + {"Center": free / 2, "End": free}.get(alignment(ref), 0)
    sizes = main_sizes(parent)
    paths = list(sizes)
    if ref.path not in paths:
        return start
    gap = max(0, parent.property("LayoutGap"))
    free = parent.property(axis) - start - end - sum(sizes.values()) - gap * max(0, len(paths) - 1)
    justify = parent.property("LayoutJustifyContent")
    offset = {"Center": free / 2, "End": free}.get(justify, 0)
    if free > 0:
        if justify == "SpaceBetween" and len(paths) > 1:
            gap += free / (len(paths) - 1)
        elif justify in ("SpaceAround", "SpaceEvenly"):
            share = free / (len(paths) if justify == "SpaceAround" else len(paths) + 1)
            offset, gap = share / 2 if justify == "SpaceAround" else share, gap + share
    index = paths.index(ref.path)
    return start + offset + sum(sizes[p] for p in paths[:index]) + gap * index


def wrapped(parent):
    """Pack by fixed sizes/flexible minimums, then allocate each flex line.

    Cross-axis free space stretches lines, matching the local flex renderer.
    Text measurement and scrollbar gutters remain host approximations.
    """
    runtime = parent.runtime
    key = ('wrap', parent.path)
    if key in runtime.layout_cache:
        return runtime.layout_cache[key]
    axis = 'Width' if parent.property('LayoutDirection') == 'Horizontal' else 'Height'
    cross = 'Height' if axis == 'Width' else 'Width'
    gap = max(0, parent.property('LayoutGap'))
    available = max(0, parent.property(axis) - sum(inset(parent, axis)))
    lines, refs, line, used = [], {}, [], 0
    for child in parent.children:
        if not child.property('Visible'):
            continue
        minimum, maximum = limits(child, axis)
        weight = max(0, child.property('FillPortions'))
        fixed = 0 if weight else child.intrinsic_dimension(axis)
        entry = (child.path, weight, fixed, minimum, maximum)
        basis = minimum if weight else bounded(fixed, minimum, maximum)
        if line and used + gap + basis > available + 1e-8:
            lines.append(line)
            line, used = [], 0
        used += (gap if line else 0) + basis
        line.append(entry)
        refs[child.path] = child
    if line:
        lines.append(line)
    geometry = {}
    # Make allocated main dimensions available during AutoHeight measurement.
    for entries in lines:
        sizes = portions(available - gap * max(0, len(entries) - 1), entries)
        for path, size in sizes.items():
            geometry[path] = {axis: size}
    runtime.layout_cache[key] = geometry
    try:
        natural, cross_sizes = [], {}
        for entries in lines:
            for path, *_ in entries:
                child = refs[path]
                cross_sizes[path] = bounded(child.intrinsic_dimension(cross), *limits(child, cross))
            natural.append(max((cross_sizes[p] for p, *_ in entries), default=0))
        cross_available = max(0, parent.property(cross) - sum(inset(parent, cross)))
        extra = max(0, cross_available - sum(natural) - gap * max(0, len(lines) - 1))
        cross_offset = inset(parent, cross)[0]
        main_coord, cross_coord = ('X', 'Y') if axis == 'Width' else ('Y', 'X')
        for entries, base in zip(lines, natural):
            line_cross = base + extra / len(lines)
            paths = [p for p, *_ in entries]
            sizes = {p: geometry[p][axis] for p in paths}
            offset, spacing = justification(parent, available - sum(sizes.values()) - gap * max(0, len(paths) - 1), len(paths), gap)
            main_offset = inset(parent, axis)[0] + offset
            for path in paths:
                child = refs[path]
                # Canvas ignores child Align-in-container overrides when wrapping.
                align = parent.property("LayoutAlignItems")
                size = bounded(line_cross, *limits(child, cross)) if align == 'Stretch' else cross_sizes[path]
                geometry[path].update({cross: size, main_coord: main_offset,
                    cross_coord: cross_offset + {'Center': (line_cross-size)/2, 'End': line_cross-size}.get(align, 0)})
                main_offset += sizes[path] + spacing
            cross_offset += line_cross + gap
        return geometry
    except Exception:
        runtime.layout_cache.pop(key, None)
        raise


def justification(parent, free, count, gap):
    justify = parent.property('LayoutJustifyContent')
    offset = {'Center': free / 2, 'End': free}.get(justify, 0)
    if free > 0:
        if justify == 'SpaceBetween' and count > 1:
            gap += free / (count - 1)
        elif justify in ('SpaceAround', 'SpaceEvenly'):
            share = free / (count if justify == 'SpaceAround' else count + 1)
            offset, gap = share / 2 if justify == 'SpaceAround' else share, gap + share
    return offset, gap


def wrapped_property(ref, name):
    result = wrapped(ref.parent).get(ref.path, {})
    if name in result:
        return result[name]
    # Hidden controls do not occupy lines. During cross-size measurement the
    # line is incomplete; use the authored dimension without hiding cycles.
    if name in ('Width', 'Height'):
        return bounded(ref.intrinsic_dimension(name), *limits(ref, name))
    return inset(ref.parent, 'Width' if name == 'X' else 'Height')[0]
