#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rr_track_converter.py
=====================

Convert OLD Rocket Racing / DelMar tracks (class `DelMarTrack_BP_C`, which Epic's
deleted brand template no longer validates) into the NEW validate-friendly device
(`Device_FortDelMarTrack_C`).

WHAT IT KEEPS EXACTLY
---------------------
  * Every spline point's position / tangent / rotation / scale  (the `SplineCurves`
    block is copied byte-for-byte).
  * The binary `Spline=SplineData ...` blob (copied byte-for-byte).
  * The `RotationalMinimalFrameNormals` table (banking / roll of every sample).
  * Each segment's TRACK TYPE and per-segment mesh customizations
    (`DelMarTrackPointData.MetaData(i)`), with the gameplay tag namespace remapped
    `DelMar.Track.*`  ->  `FortDelMar.Track.*`  (this is what the new device reads).
  * The exact WORLD location & rotation of the whole track (see "Transform" below).
  * Track-to-track connections (`StartTrackConnection` / `EndTrackConnection`) — the
    references are renamed in lock-step so links between converted pieces survive.

WHY YOUR FRIEND'S VERSION WENT INVISIBLE
----------------------------------------
The new device renders its road mesh from the per-segment gameplay tags in
`DelMarTrackPointData.MetaData(i).TrackTypeTag`.  In the new build those tags were
renamed from `DelMar.Track.*` to `FortDelMar.Track.*`.  If you keep the OLD tag
strings (or start from an empty template and drop the MetaData), the device cannot
resolve the type, enables no mesh customizations, and the track is invisible even
though the spline is still there.  This script remaps every tag and carries the
MetaData across, so the road shows up.

THE TRANSFORM (why locations are preserved exactly)
---------------------------------------------------
  OLD:  RootComponent = MainSpline.  The spline IS the root and holds the track's
        world RelativeLocation / RelativeRotation.  Spline points are local to it.
  NEW:  RootComponent = StaticMeshComponent0.  It holds the world transform and the
        spline is attached underneath it at identity.
  So we MOVE the old MainSpline's RelativeLocation / RelativeRotation onto the new
  StaticMeshComponent0 and leave the (unchanged) local spline points alone.  Same
  local points + same world transform  ==  pixel-identical track placement.

USAGE
-----
  # EASIEST — clipboard mode (this is the DEFAULT when you give no file, and what happens
  # if you just double-click the program): copy your old tracks in UEFN (Ctrl+C), run this,
  # then paste back into UEFN (Ctrl+V).
  python rr_track_converter.py

  # Drag a UEFN-exported .txt onto the program, OR pass it explicitly -> writes
  # "<name>_CONVERTED.txt" next to it:
  python rr_track_converter.py  old_tracks.txt

  # File in, file out:
  python rr_track_converter.py  old_tracks.txt  new_tracks.txt

THE UEFN WORKFLOW
-----------------
  1. In UEFN, select your old track pieces and press Ctrl+C  (or use the provided
     OLD .txt export).
  2. Run this script (clipboard mode, or paste the copied text into a .txt and use
     file mode).
  3. Delete the old (broken) track pieces from the level.
  4. Paste (Ctrl+V) the converted text into the level — the new devices appear in the
     exact same spot with the same shapes and types, and they validate.

This script only uses the Python standard library, so it runs in UEFN's embedded
Python or any normal Python 3.6+.
"""

import argparse
import os
import re
import sys
import uuid

# --------------------------------------------------------------------------------------
# Configuration — edit these if Epic renames things again, or to tweak behaviour.
# --------------------------------------------------------------------------------------

# Cosmetic: the old tracks used a very short 2800 cull distance.  The new device uses
# ~23263, so distant parts of large tracks don't pop out.  Set to None to keep originals.
NEW_DRAW_DISTANCE = "23263.666016"

# Give every converted actor a brand-new SavedActorGuid so it can never collide with the
# original it was made from.  (Connections key off actor NAME, not GUID, so this is safe.)
REGENERATE_GUIDS = True

# The new device's playset path (constant across every new track template).
PLAYSET_PACKAGE_PATH = "/CRD_FortDelMarTrack/SetupAssets/PID_CP_Devices_FortDelMarTrack"

# Old editor sprite material (deleted with the old brand) -> the new device's sprite material.
OLD_SPRITE_MATERIAL = ("/DelMarGame/Track/Shared/PhysicalMaterials/"
                       "MI_CP_Device_DelMarTrack_Placed_01.MI_CP_Device_DelMarTrack_Placed_01")
NEW_SPRITE_MATERIAL = ("/FortDelMarTrack/Thumbnails/Device/"
                       "MI_CP_Device_FortDelMarTrack.MI_CP_Device_FortDelMarTrack")

# Ordered, anchored string substitutions.  ORDER MATTERS — see the comments.
# Each tuple is (old, new).  These never touch the hex `SplineData` blob because every
# pattern contains a '/', '.', or a quote, none of which occur inside the hex.
IDENTIFIER_SUBSTITUTIONS = [
    # 1. Sprite-icon archetype lives in a DIFFERENT package than the device class, so it
    #    must be rewritten BEFORE the generic actor-class rule (#8) below.
    ("/DelMarGame/Track/DelMarTrack_BP.DelMarTrack_BP_C:SpriteIcon_GEN_VARIABLE",
     "/FortDelMarTrack/BP_FortDelMarTrack.BP_FortDelMarTrack_C:SpriteIcon_GEN_VARIABLE"),
    # 2 & 3. Snap + spline component names (class AND instance names both gain the Fort prefix).
    ("DelMarTrackSnapToSplinePointComponent", "FortDelMarTrackSnapToSplinePointComponent"),
    ("DelMarTrackSplineComponent",            "FortDelMarTrackSplineComponent"),
    # 4. PointData CLASS only.  The component's *instance* name stays "DelMarTrackPointData"
    #    in the new format, so we anchor on the /Script/ path and do NOT rename the instance.
    ("/Script/DelMarTrackRuntime.DelMarTrackPointData",
     "/Script/FortDelMarTrackRuntime.FortDelMarTrackPointData"),
    # 5. Catch-all for the runtime module (fixes the module path on the snap/spline classes
    #    whose class names were already renamed in #2/#3).
    ("/Script/DelMarTrackRuntime.", "/Script/FortDelMarTrackRuntime."),
    # 6. Archetype default object (the "Default__" CDO) -> new device CDO.  Before #8.
    ("/DelMarGame/Track/DelMarTrack_BP.Default__DelMarTrack_BP_C",
     "/CRD_FortDelMarTrack/Device_FortDelMarTrack.Default__Device_FortDelMarTrack_C"),
    # 7. Generic actor class path -> new device class path.
    ("/DelMarGame/Track/DelMarTrack_BP.DelMarTrack_BP_C",
     "/CRD_FortDelMarTrack/Device_FortDelMarTrack.Device_FortDelMarTrack_C"),
    # 8. Actor INSTANCE name prefix (keeps the unique _UAID_ suffix so names stay unique and
    #    connection references keep pointing at the right converted actor).
    ("DelMarTrack_BP_C_UAID_", "Device_FortDelMarTrack_C_UAID_"),
    # 9. Old sprite material -> new sprite material.
    (OLD_SPRITE_MATERIAL, NEW_SPRITE_MATERIAL),
]

# ----------------------------- Gameplay-tag (track TYPE) remap -----------------------------
# The new device picks each segment's road/guardrail/tunnel mesh from this per-segment tag, so
# getting it right is what keeps the road visible (this is exactly what the friend's version got
# wrong). The namespace was renamed DelMar.Track.* -> FortDelMar.Track.*.
#
# These NEW tags are CONFIRMED to exist (every one appears in a Resources/Different_NEW_TrackTypes
# template). Any produced tag NOT in this set is flagged at the end of a run so you can verify it
# in UEFN (Window > Gameplay Tag List) and, if needed, correct TAG_MAP below.
CONFIRMED_NEW_TAGS = {
    "",  # empty = "no road here" (New_RR_Track_NONE.txt); valid and resolvable
    "FortDelMar.Track.Basic.Default.GuardrailNone",
    "FortDelMar.Track.Basic.Default.GuardrailLeft",
    "FortDelMar.Track.Basic.Default.GuardrailRight",
    "FortDelMar.Track.Basic.Default.GuardrailBoth",
    "FortDelMar.Track.Basic.HazardLanes.GuardrailNone",
    "FortDelMar.Track.Basic.HazardLanes.GuardrailLeft",
    "FortDelMar.Track.Basic.HazardLanes.GuardrailRight",
    "FortDelMar.Track.Basic.HazardLanes.GuardrailBoth",
    "FortDelMar.Track.Banked.Default.GuardrailNone",
    "FortDelMar.Track.Banked.Default.GuardrailLeft",
    "FortDelMar.Track.Banked.Default.GuardrailRight",
    "FortDelMar.Track.Banked.Default.GuardrailBoth",
    "FortDelMar.Track.Halfpipe.Default.Uniform",
    "FortDelMar.Track.Pipe.Default.Uniform",
    "FortDelMar.Track.Tunnel.Default.Wide",
    "FortDelMar.Track.Tunnel.Default.Wide.SolidCeiling",
}

# Explicit OLD -> NEW overrides. If you discover a tag that needs a hand-picked target (because
# Epic dropped or renamed it), add it here and it wins over the default rule below.
# NOTE on "DelMar.Track.Hidden": it is intentionally a road-less STRUCTURAL segment (it also
# carries bForceValidTrack to keep the track continuous through invisible connectors), so we
# preserve it as FortDelMar.Track.Hidden rather than blanking it — blanking would risk breaking
# track continuity/validation. Override here only if UEFN confirms that tag is gone.
TAG_MAP = {
    # "DelMar.Track.Hidden": "FortDelMar.Track.Hidden",        # == default rule (shown for clarity)
    # "DelMar.Track": "FortDelMar.Track.Basic.Default.GuardrailNone",   # example hand-pick
}


def remap_tag(old_tag):
    """Map one OLD TagName to its NEW equivalent. Explicit TAG_MAP wins; otherwise swap the
    leading 'DelMar.' for 'FortDelMar.' (empty stays empty)."""
    if old_tag in TAG_MAP:
        return TAG_MAP[old_tag]
    if old_tag == "":
        return ""
    if old_tag.startswith("DelMar."):
        return "FortDelMar." + old_tag[len("DelMar."):]
    return old_tag  # already-new or foreign tag: leave untouched


def _remap_tags(text, produced=None):
    def repl(m):
        new = remap_tag(m.group(1))
        if produced is not None:
            produced.append(new)
        return 'TagName="%s"' % new
    return re.sub(r'TagName="([^"]*)"', repl, text)

OLD_ACTOR_CLASS_MARKER = "/DelMarGame/Track/DelMarTrack_BP.DelMarTrack_BP_C"
DEFAULT_OLD_RESOURCE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "Resources", "TrackThatNeedsReplacement", "TracksThatNeedsToBeReplaced_OLD.txt")


# --------------------------------------------------------------------------------------
# Tiny T3D (UE copy/paste text) tree parser.  Keeps every untouched line byte-for-byte.
# --------------------------------------------------------------------------------------

def _make_node(header=None):
    return {"header": header, "body": [], "footer": None}


def parse_t3d(lines):
    """Parse lines into a tree. Pushes only on 'Begin Object'/'Begin Actor', pops on
    exactly 'End Object'/'End Actor'.  'Begin Map/Level/Surface' etc. stay as raw lines."""
    root = _make_node()
    stack = [root]
    for line in lines:
        s = line.strip()
        if s.startswith("Begin Object") or s.startswith("Begin Actor"):
            node = _make_node(line)
            stack[-1]["body"].append(node)
            stack.append(node)
        elif s == "End Object" or s == "End Actor":
            if len(stack) > 1:
                stack.pop()["footer"] = line
            else:                       # unbalanced End — keep it as a raw line, don't crash
                stack[-1]["body"].append(line)
        else:
            stack[-1]["body"].append(line)
    return root


def serialize_t3d(node, out):
    if node["header"] is not None:
        out.append(node["header"])
    for item in node["body"]:
        if isinstance(item, str):
            out.append(item)
        else:
            serialize_t3d(item, out)
    if node["footer"] is not None:
        out.append(node["footer"])
    return out


# --------------------------------------------------------------------------------------
# Node helpers
# --------------------------------------------------------------------------------------

def _children(node):
    return [it for it in node["body"] if isinstance(it, dict)]


def _obj_name(node):
    m = re.search(r'Name="([^"]+)"', node["header"] or "")
    return m.group(1) if m else None


def _is_decl(node):
    # A declaration header carries 'Class='. A body header is just 'Begin Object Name="..."'.
    return "Class=" in (node["header"] or "")


def _find_object(actor, name, decl):
    for it in _children(actor):
        if _obj_name(it) == name and _is_decl(it) == decl:
            return it
    return None


def _strip_starts(line, prefix):
    return isinstance(line, str) and line.strip().startswith(prefix)


# --------------------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------------------

class ConversionError(Exception):
    pass


def _apply_string_substitutions(text, produced_tags=None):
    for old, new in IDENTIFIER_SUBSTITUTIONS:
        text = text.replace(old, new)
    text = _remap_tags(text, produced_tags)
    if NEW_DRAW_DISTANCE:
        text = re.sub(r"CachedMaxDrawDistance=[0-9.]+",
                      "CachedMaxDrawDistance=" + NEW_DRAW_DISTANCE, text)
        text = re.sub(r"CullDistance=[0-9.]+",
                      "CullDistance=" + NEW_DRAW_DISTANCE, text)
    return text


def _build_component_node(text):
    """Parse a small T3D snippet (one Begin Object...End Object) into a node."""
    root = parse_t3d(text.split("\n"))
    return _children(root)[0]


def _new_components(level_prefix, new_name):
    """Return (toy_decl, mini_decl, toy_body, mini_body) nodes for the new device shell."""
    toy_type = "/Game/Items/Traps/Blueprints/Toys/ToyOptionsComponent.ToyOptionsComponent_C"
    mini_type = "/Script/FortniteGame.FortMinigameProgressComponent"
    toy_decl = _build_component_node(
        '         Begin Object Class={t} Name="ToyOptionsComponent" '
        'Archetype="{t}\'/CRD_FortDelMarTrack/Device_FortDelMarTrack.Device_FortDelMarTrack_C'
        ':ToyOptionsComponent_GEN_VARIABLE\'" '
        'ExportPath="{t}\'{lp}.{n}.ToyOptionsComponent\'"\n'
        '         End Object'.format(t=toy_type, lp=level_prefix, n=new_name))
    mini_decl = _build_component_node(
        '         Begin Object Class={t} Name="FortMinigameProgress" '
        'Archetype="{t}\'/CRD_FortDelMarTrack/Device_FortDelMarTrack.Device_FortDelMarTrack_C'
        ':FortMinigameProgress_GEN_VARIABLE\'" '
        'ExportPath="{t}\'{lp}.{n}.FortMinigameProgress\'"\n'
        '         End Object'.format(t=mini_type, lp=level_prefix, n=new_name))
    toy_body = _build_component_node(
        '         Begin Object Name="ToyOptionsComponent" '
        'ExportPath="{t}\'{lp}.{n}.ToyOptionsComponent\'"\n'
        '            PlayerOptionData=(PropertyOverrides=((PropertyName="LabelOverride"),'
        '(PropertyName="ShowSplinePointNumbers",PropertyData="False")))\n'
        '            UCSSerializationIndex=0\n'
        '            bNetAddressable=True\n'
        '            CreationMethod=SimpleConstructionScript\n'
        '         End Object'.format(t=toy_type, lp=level_prefix, n=new_name))
    mini_body = _build_component_node(
        '         Begin Object Name="FortMinigameProgress" '
        'ExportPath="{t}\'{lp}.{n}.FortMinigameProgress\'"\n'
        '            UCSSerializationIndex=0\n'
        '            bNetAddressable=True\n'
        '            CreationMethod=SimpleConstructionScript\n'
        '         End Object'.format(t=mini_type, lp=level_prefix, n=new_name))
    return toy_decl, mini_decl, toy_body, mini_body


def _move_transform_to_static_mesh(actor, report):
    """Move MainSpline's world RelativeLocation/RelativeRotation onto StaticMeshComponent0
    and parent the spline under it (the heart of preserving exact placement)."""
    spline = _find_object(actor, "MainSpline", decl=False)
    smc = _find_object(actor, "StaticMeshComponent0", decl=False)
    if spline is None or smc is None:
        raise ConversionError("could not find MainSpline/StaticMeshComponent0 body objects")

    moved, kept = [], []
    for item in spline["body"]:
        if _strip_starts(item, "RelativeLocation=") or _strip_starts(item, "RelativeRotation="):
            moved.append(item)
        else:
            kept.append(item)
    spline["body"] = kept

    # Spline must now be attached to the static mesh (it was the root before).
    if not any(_strip_starts(i, "AttachParent=") for i in spline["body"]):
        spline["body"].append('            AttachParent="StaticMeshComponent0"')

    # Drop any transform already on the static mesh, then graft the spline's transform on.
    smc["body"] = [i for i in smc["body"]
                   if not (_strip_starts(i, "RelativeLocation=")
                           or _strip_starts(i, "RelativeRotation="))]
    smc["body"].extend(moved)
    report["moved_transform"] = len(moved) > 0
    return moved


def _edit_actor_properties(actor, new_name):
    """Rewrite the actor-level property lines: root component, add the device-shell refs
    and playset path, refresh the GUID."""
    body = actor["body"]

    # RootComponent: MainSpline -> StaticMeshComponent0
    for i, item in enumerate(body):
        if _strip_starts(item, "RootComponent="):
            body[i] = '         RootComponent="StaticMeshComponent0"'
            break

    # Fresh GUID so it can't clash with the original actor.
    if REGENERATE_GUIDS:
        for i, item in enumerate(body):
            if _strip_starts(item, "SavedActorGuid="):
                body[i] = "         SavedActorGuid=" + uuid.uuid4().hex.upper()
                break

    # Insert the two component back-references (FortMinigameProgress / ToyOptionsComponent)
    # just before the existing SpriteIcon="SpriteIcon" actor property, matching the template.
    refs = ['         FortMinigameProgress="FortMinigameProgress"',
            '         ToyOptionsComponent="ToyOptionsComponent"']
    sprite_idx = next((i for i, it in enumerate(body) if _strip_starts(it, "SpriteIcon=")), None)
    if sprite_idx is not None:
        body[sprite_idx:sprite_idx] = refs
    else:
        body.extend(refs)

    # PlaysetPackagePathName just before SavedActorGuid (or at the end if not present).
    playset = '         PlaysetPackagePathName="{0}"'.format(PLAYSET_PACKAGE_PATH)
    if not any(_strip_starts(it, "PlaysetPackagePathName=") for it in body):
        guid_idx = next((i for i, it in enumerate(body) if _strip_starts(it, "SavedActorGuid=")),
                        None)
        if guid_idx is not None:
            body.insert(guid_idx, playset)
        else:
            body.append(playset)


def _insert_shell_components(actor, level_prefix, new_name):
    toy_decl, mini_decl, toy_body, mini_body = _new_components(level_prefix, new_name)
    body = actor["body"]

    # Declarations: right after the SpriteIcon declaration object.
    sprite_decl = _find_object(actor, "SpriteIcon", decl=True)
    if sprite_decl is not None and sprite_decl in body:
        idx = body.index(sprite_decl)
        body[idx + 1:idx + 1] = [toy_decl, mini_decl]
    else:
        # Fall back: put them before the first actor-level property line.
        first_prop = next((i for i, it in enumerate(body) if isinstance(it, str)), len(body))
        body[first_prop:first_prop] = [toy_decl, mini_decl]

    # Bodies: right after the SpriteIcon body object.
    sprite_body = _find_object(actor, "SpriteIcon", decl=False)
    if sprite_body is not None and sprite_body in body:
        idx = body.index(sprite_body)
        body[idx + 1:idx + 1] = [toy_body, mini_body]
    else:
        first_prop = next((i for i, it in enumerate(body) if isinstance(it, str)), len(body))
        body[first_prop:first_prop] = [toy_body, mini_body]


def _extract_level_prefix(actor_header):
    """Pull '/Map/Map.Map:PersistentLevel' out of the actor's ExportPath so inserted
    components reference the SAME level the rest of the actor does (portable across maps)."""
    m = re.search(r"ExportPath=\"[^\"]*?'([^']*:PersistentLevel)\.", actor_header)
    if m:
        return m.group(1)
    return "/Game/Map.Map:PersistentLevel"


def convert_actor(actor_node, report):
    """Convert one parsed Actor node IN PLACE-ish: returns a fresh converted node."""
    # 1) String-level identity + tag + material + cull substitutions on the whole actor.
    text = "\n".join(serialize_t3d(actor_node, []))
    produced_tags = []
    text = _apply_string_substitutions(text, produced_tags)
    report["produced_tags"] = produced_tags

    # 2) Re-parse the rewritten actor.
    actor = _children(parse_t3d(text.split("\n")))[0]

    # 3) Identify new name + level prefix for component wiring.
    new_name = _obj_name_from_actor(actor["header"])
    level_prefix = _extract_level_prefix(actor["header"])
    report["name"] = new_name

    # 4) Re-home the world transform (exact placement preserved).
    _move_transform_to_static_mesh(actor, report)

    # 5) Add the new device-shell components + actor properties.
    _insert_shell_components(actor, level_prefix, new_name)
    _edit_actor_properties(actor, new_name)

    # 6) Collect a per-actor report.
    pd = _find_object(actor, "DelMarTrackPointData", decl=False)
    tags = []
    if pd is not None:
        for it in pd["body"]:
            if isinstance(it, str):
                m = re.search(r'TagName="([^"]*)"', it)
                if m:
                    tags.append(m.group(1) or "(none)")
    report["segments"] = len(tags)
    report["tags"] = tags
    return actor


def _obj_name_from_actor(actor_header):
    m = re.search(r"Name=(\S+)", actor_header)
    return m.group(1) if m else "UnknownActor"


def convert_text(text):
    """Convert a full T3D clipboard/file payload. Returns (converted_text, reports)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tree = parse_t3d(lines)

    reports = []
    converted_count = 0
    drop = set()
    for i, item in enumerate(tree["body"]):
        if isinstance(item, dict) and item["header"] and item["header"].lstrip().startswith("Begin Actor"):
            if OLD_ACTOR_CLASS_MARKER not in item["header"]:
                # Not an old DelMar track — leave it untouched so mixed selections are safe.
                continue
            report = {}
            try:
                tree["body"][i] = convert_actor(item, report)
                report["ok"] = True
                converted_count += 1
            except ConversionError as exc:
                report["ok"] = False
                report["error"] = str(exc)
                report["name"] = _obj_name_from_actor(item["header"])
                drop.add(i)                       # don't emit a half-broken/old-class actor
            reports.append(report)

    if drop:
        tree["body"] = [it for j, it in enumerate(tree["body"]) if j not in drop]

    out_lines = serialize_t3d(tree, [])
    converted_text = "\r\n".join(out_lines)
    if not converted_text.endswith("\r\n"):
        converted_text += "\r\n"
    return converted_text, reports, converted_count


# --------------------------------------------------------------------------------------
# Clipboard (Windows) — optional, std-lib only, never fatal.
# --------------------------------------------------------------------------------------

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _win_clipboard():
    """Return (ctypes, u32, k32) with restype/argtypes set so 64-bit HANDLEs marshal as
    pointers (not c_int). Without this, GlobalAlloc's >32-bit handle overflows on 64-bit Python."""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.restype = wintypes.BOOL
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.restype = wintypes.HGLOBAL
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u32.OpenClipboard.restype = wintypes.BOOL
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.CloseClipboard.restype = wintypes.BOOL
    u32.CloseClipboard.argtypes = []
    u32.EmptyClipboard.restype = wintypes.BOOL
    u32.EmptyClipboard.argtypes = []
    u32.GetClipboardData.restype = wintypes.HANDLE
    u32.GetClipboardData.argtypes = [wintypes.UINT]
    u32.SetClipboardData.restype = wintypes.HANDLE
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    return ctypes, u32, k32


def get_clipboard_text():
    try:
        ctypes, u32, k32 = _win_clipboard()
        if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        if not u32.OpenClipboard(None):
            return None
        try:
            handle = u32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            ptr = k32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.c_wchar_p(ptr).value
            finally:
                k32.GlobalUnlock(handle)
        finally:
            u32.CloseClipboard()
    except Exception as exc:                                       # noqa: BLE001
        print("  (clipboard read failed: {0})".format(exc))
        return None


def set_clipboard_text(text):
    try:
        ctypes, u32, k32 = _win_clipboard()
        buf = ctypes.create_unicode_buffer(text)   # NUL-terminated copy of the string
        size = ctypes.sizeof(buf)
        h = k32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h:
            return False
        ptr = k32.GlobalLock(h)
        if not ptr:
            k32.GlobalFree(h)
            return False
        ctypes.memmove(ptr, buf, size)
        k32.GlobalUnlock(h)
        if not u32.OpenClipboard(None):
            k32.GlobalFree(h)
            return False
        try:
            u32.EmptyClipboard()
            if not u32.SetClipboardData(CF_UNICODETEXT, h):
                k32.GlobalFree(h)               # we still own it on failure
                return False
            return True                          # success: the OS owns the handle now
        finally:
            u32.CloseClipboard()
    except Exception as exc:                                       # noqa: BLE001
        print("  (clipboard write failed: {0})".format(exc))
        return False


# --------------------------------------------------------------------------------------
# Reporting + CLI
# --------------------------------------------------------------------------------------

def print_report(reports, converted_count):
    print("-" * 70)
    if not reports:
        print("No old DelMarTrack_BP actors were found in the input.")
        print("(Make sure you copied the OLD tracks, not already-converted ones.)")
        return
    tag_counts = {}
    for r in reports:
        if r.get("ok"):
            tags = [t for t in r.get("tags", []) if t and t != "(none)"]
            for t in tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
            print("  OK  {0}".format(r.get("name", "?")))
            print("      segments: {0}   transform re-homed: {1}".format(
                r.get("segments", 0), "yes" if r.get("moved_transform") else "NO (!)"))
            uniq = sorted(set(tags))
            if uniq:
                print("      types: " + ", ".join(uniq))
        else:
            print("  FAIL {0}: {1}  (left OUT of the output)".format(
                r.get("name", "?"), r.get("error")))
    print("-" * 70)
    print("Converted {0} track actor(s).".format(converted_count))

    # Surface any produced type tag we can't confirm against the NEW templates. They are very
    # likely valid (same namespace), but this is the one place an invisible segment could hide,
    # so we name them explicitly instead of pretending everything is verified.
    unconfirmed = sorted((t, c) for t, c in tag_counts.items() if t not in CONFIRMED_NEW_TAGS)
    if unconfirmed:
        print("")
        print("NOTE - these track-type tags were preserved from your old tracks but are NOT in the")
        print("       NEW template set, so I couldn't 100% confirm them. They should be fine, but")
        print("       IF a converted segment looks invisible, check that tag exists in UEFN")
        print("       (Window > Gameplay Tag List); if it doesn't, add a fix to TAG_MAP in this script:")
        for t, c in unconfirmed:
            print("         - {0}   ({1} segment(s))".format(t, c))

    failed = sum(1 for r in reports if not r.get("ok"))
    if failed:
        print("")
        print("WARNING: {0} actor(s) failed to convert and were left out of the output.".format(failed))


def _owns_console():
    """True when this process is the ONLY one attached to the console — i.e. it was double-
    clicked from Explorer and the window will vanish on exit, so we should pause. Windows only."""
    try:
        import ctypes
        arr = (ctypes.c_uint * 2)()
        return ctypes.windll.kernel32.GetConsoleProcessList(arr, 2) <= 1
    except Exception:                                             # noqa: BLE001
        return False


def _maybe_pause():
    if _owns_console():
        try:
            input("\nPress Enter to close this window...")
        except (EOFError, KeyboardInterrupt):
            pass


def run_clipboard():
    text = get_clipboard_text()
    if not text or "Begin Actor" not in text:
        print("I couldn't find any track data on your clipboard.\n"
              "In UEFN: select your OLD track pieces, press Ctrl+C, then run this again.")
        return 2
    converted, reports, n = convert_text(text)
    print_report(reports, n)
    if n == 0:
        return 1
    partial = 3 if any(not r.get("ok") for r in reports) else 0
    if set_clipboard_text(converted):
        print("\nConverted! The NEW tracks are now on your clipboard.")
        print("Switch to UEFN, delete the old pieces, and press Ctrl+V.")
        return partial
    fallback = os.path.join(os.path.expanduser("~"), "converted_NEW_tracks.txt")
    try:
        _write(fallback, converted)
        print("\n(Couldn't set the clipboard, so I saved the result to:\n  {0}\n"
              "Open it, Ctrl+A, Ctrl+C, then paste into UEFN.)".format(fallback))
        return partial
    except OSError as exc:                                        # noqa: BLE001
        print("Clipboard and file write both failed: {0}".format(exc))
        return 1


def run_file(in_path, out_path):
    if not os.path.isfile(in_path):
        print("Input file not found: {0}".format(in_path))
        return 2
    if not out_path:
        base, ext = os.path.splitext(in_path)
        out_path = base + "_CONVERTED" + (ext or ".txt")
    with open(in_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    print("Input : {0}".format(in_path))
    converted, reports, n = convert_text(text)
    print_report(reports, n)
    if n == 0:
        return 1
    _write(out_path, converted)
    print("Output: {0}".format(out_path))
    print("Open it, Ctrl+A, Ctrl+C, then paste into UEFN (after deleting the old pieces).")
    return 3 if any(not r.get("ok") for r in reports) else 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Convert old Rocket Racing / DelMar tracks to the new validate-friendly "
                    "Device_FortDelMarTrack device, preserving spline points and types.")
    p.add_argument("input", nargs="?",
                   help="input .txt (a UEFN copy/paste export, or a file dragged onto this "
                        "program). Omit to read/write the clipboard instead.")
    p.add_argument("output", nargs="?", help="output .txt. Omit to derive from the input name.")
    p.add_argument("-c", "--clipboard", action="store_true",
                   help="force clipboard mode (also the default when no input file is given).")
    args = p.parse_args(argv)

    print("=" * 70)
    print("  Rocket Racing / DelMar track converter  ->  new FortDelMar device")
    print("=" * 70)

    if args.input and not args.clipboard:
        code = run_file(args.input, args.output)
    else:
        print("No file given - using CLIPBOARD mode.")
        print("(First copy your old tracks in UEFN with Ctrl+C.)\n")
        code = run_clipboard()

    _maybe_pause()
    return code


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


if __name__ == "__main__":
    sys.exit(main())
