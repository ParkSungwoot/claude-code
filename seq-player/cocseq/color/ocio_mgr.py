"""OpenColorIO: config loading, color space menus and GPU shader generation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

try:
    import PyOpenColorIO as ocio
except Exception as exc:  # pragma: no cover
    ocio = None
    log.error("OpenColorIO unavailable: %s", exc)

BUILTIN_CONFIGS = [
    ("ACES Studio (내장)", "ocio://studio-config-latest"),
    ("ACES CG (내장)", "ocio://cg-config-latest"),
]


@dataclass
class GpuTexture:
    sampler: str
    kind: str            # "1d" | "2d" | "3d"
    width: int
    height: int
    channels: int        # 1 or 3
    linear: bool
    values: np.ndarray


@dataclass
class GpuFunction:
    name: str
    text: str
    textures: list[GpuTexture] = field(default_factory=list)
    uniforms: list[tuple[str, str, object]] = field(default_factory=list)   # name, type, value


@dataclass
class ColorPipeline:
    key: tuple
    to_lin: GpuFunction
    to_disp: GpuFunction
    error: str = ""


def _identity(name: str) -> GpuFunction:
    return GpuFunction(name, f"vec4 {name}(vec4 c) {{ return c; }}\n")


def _srgb_decode(name: str) -> GpuFunction:
    return GpuFunction(name, f"""
vec4 {name}(vec4 c) {{
    vec3 x = c.rgb;
    vec3 lo = x / 12.92;
    vec3 hi = pow(max((x + 0.055) / 1.055, vec3(0.0)), vec3(2.4));
    return vec4(mix(lo, hi, step(vec3(0.04045), x)), c.a);
}}
""")


def _srgb_encode(name: str) -> GpuFunction:
    return GpuFunction(name, f"""
vec4 {name}(vec4 c) {{
    vec3 x = max(c.rgb, vec3(0.0));
    vec3 lo = x * 12.92;
    vec3 hi = 1.055 * pow(x, vec3(1.0 / 2.4)) - 0.055;
    return vec4(mix(lo, hi, step(vec3(0.0031308), x)), c.a);
}}
""")


class ColorManager:
    def __init__(self):
        self.config = None
        self.uri = ""
        self.error = ""
        self._pipelines: dict[tuple, ColorPipeline] = {}
        self._cpu: dict[tuple, object] = {}

    @property
    def available(self) -> bool:
        return self.config is not None

    # ---------------------------------------------------------------- config

    def load(self, uri: str, prefer_env: bool = True) -> bool:
        env = os.environ.get("OCIO", "")
        candidates = []
        if prefer_env and env:
            candidates.append(env)
        if uri:
            candidates.append(uri)
        candidates.append("ocio://studio-config-latest")
        self.error = ""
        if ocio is None:
            self.error = "OpenColorIO를 불러오지 못했습니다."
            self.config = None
            return False
        for cand in candidates:
            try:
                cfg = ocio.Config.CreateFromFile(cand)
                cfg.validate()
            except Exception as exc:
                self.error = f"{cand}: {exc}"
                log.warning("OCIO config %s failed: %s", cand, exc)
                continue
            self.config = cfg
            self.uri = cand
            self._pipelines.clear()
            self._cpu.clear()
            if cand != (candidates[0] if candidates else cand):
                log.info("OCIO config fallback: %s", cand)
            return True
        self.config = None
        return False

    def config_label(self) -> str:
        for label, uri in BUILTIN_CONFIGS:
            if uri == self.uri:
                return label
        return os.path.basename(self.uri) if self.uri else "없음"

    # ---------------------------------------------------------------- menus

    def colorspaces(self) -> list[tuple[str, str]]:
        """(family, name) of every color space, config order."""
        if not self.config:
            return [("", "sRGB"), ("", "Linear")]
        out = []
        for cs in self.config.getColorSpaces():
            out.append((cs.getFamily() or "", cs.getName()))
        return out

    def displays(self) -> list[str]:
        if not self.config:
            return ["sRGB"]
        return list(self.config.getDisplays())

    def views(self, display: str) -> list[str]:
        if not self.config:
            return ["Standard"]
        try:
            return list(self.config.getViews(display))
        except Exception:
            return []

    def looks(self) -> list[str]:
        if not self.config:
            return []
        return list(self.config.getLookNames())

    def default_display(self) -> str:
        return self.config.getDefaultDisplay() if self.config else "sRGB"

    def default_view(self, display: str) -> str:
        return self.config.getDefaultView(display) if self.config else "Standard"

    def resolve_display_view(self, display: str, view: str) -> tuple[str, str]:
        displays = self.displays()
        if display not in displays:
            display = self.default_display() if self.config else displays[0]
        views = self.views(display)
        if view not in views:
            view = self.default_view(display) if self.config else (views[0] if views else "")
        return display, view

    def resolve_colorspace(self, name: str, role: str = "scene_linear") -> str:
        if not self.config:
            return name or "sRGB"
        if name:
            cs = self.config.getColorSpace(name)
            if cs is not None:
                return cs.getName()
        for r in (role, "scene_linear", "default"):
            try:
                cs = self.config.getColorSpace(r)
            except Exception:
                cs = None
            if cs is not None:
                return cs.getName()
        names = list(self.config.getColorSpaceNames())
        return names[0] if names else ""

    def default_colorspace(self, source, prefs) -> str:
        if source.kind == "movie":
            return self.resolve_colorspace(prefs.cs_movie, "color_picking")
        if source.info.is_float:
            return self.resolve_colorspace(prefs.cs_float, "scene_linear")
        return self.resolve_colorspace(prefs.cs_int, "color_picking")

    def is_data(self, name: str) -> bool:
        if not self.config or not name:
            return False
        cs = self.config.getColorSpace(name)
        return bool(cs and cs.isData())

    # ---------------------------------------------------------------- processors

    def _display_transform(self, display: str, view: str, look: str, lut: str, lut_mode: str):
        dvt = ocio.DisplayViewTransform(src=ocio.ROLE_SCENE_LINEAR, display=display, view=view)
        group = ocio.GroupTransform()
        if look:
            group.appendTransform(ocio.LookTransform(src=ocio.ROLE_SCENE_LINEAR, dst=ocio.ROLE_SCENE_LINEAR,
                                                     looks=look))
        group.appendTransform(dvt)
        if lut and lut_mode == "after":
            group.appendTransform(ocio.FileTransform(src=lut, interpolation=ocio.INTERP_BEST))
        return group

    def _extract(self, processor, fname: str, prefix: str) -> GpuFunction:
        gpu = processor.getDefaultGPUProcessor()
        desc = ocio.GpuShaderDesc.CreateShaderDesc(
            language=ocio.GPU_LANGUAGE_GLSL_4_0, functionName=fname, resourcePrefix=prefix)
        gpu.extractGpuShaderInfo(desc)
        fn = GpuFunction(fname, desc.getShaderText())
        for t in desc.getTextures():
            ch = 1 if str(t.channel).endswith("RED_CHANNEL") else 3
            kind = "1d" if str(t.dimensions).endswith("TEXTURE_1D") else "2d"
            fn.textures.append(GpuTexture(
                t.samplerName, kind, int(t.width), int(t.height), ch,
                str(t.interpolation).endswith("INTERP_LINEAR"),
                np.ascontiguousarray(t.getValues(), np.float32)))
        for t in desc.get3DTextures():
            fn.textures.append(GpuTexture(
                t.samplerName, "3d", int(t.edgeLen), int(t.edgeLen), 3,
                not str(t.interpolation).endswith("INTERP_NEAREST"),
                np.ascontiguousarray(t.getValues(), np.float32)))
        for name, u in desc.getUniforms():
            typ = str(u.type).split(".")[-1]
            try:
                if typ == "UNIFORM_DOUBLE":
                    val = u.getDouble()
                elif typ == "UNIFORM_BOOL":
                    val = u.getBool()
                elif typ == "UNIFORM_FLOAT3":
                    val = tuple(u.getFloat3())
                elif typ == "UNIFORM_VECTOR_FLOAT":
                    val = list(u.getVectorFloat())
                elif typ == "UNIFORM_VECTOR_INT":
                    val = list(u.getVectorInt())
                else:
                    continue
            except Exception:
                continue
            fn.uniforms.append((name, typ, val))
        return fn

    def pipeline(self, src: str, display: str, view: str, look: str = "", lut: str = "",
                 lut_mode: str = "after") -> ColorPipeline:
        key = (self.uri, src, display, view, look, lut, lut_mode)
        cached = self._pipelines.get(key)
        if cached is not None:
            return cached
        pipe = self._build(key, src, display, view, look, lut, lut_mode)
        self._pipelines[key] = pipe
        return pipe

    def _fallback(self, key: tuple, src: str, error: str) -> ColorPipeline:
        encoded = any(t in src.lower() for t in ("srgb", "encoded", "texture", "display", "rec.1886", "gamma"))
        to_lin = _srgb_decode("ocio_lin") if encoded else _identity("ocio_lin")
        return ColorPipeline(key, to_lin, _srgb_encode("ocio_disp"), error)

    def _build(self, key, src, display, view, look, lut, lut_mode) -> ColorPipeline:
        if not self.config:
            return self._fallback(key, src, self.error or "OCIO 설정 없음")
        cfg = self.config
        try:
            if lut and lut_mode == "replace":
                to_lin = _identity("ocio_lin")
                proc = cfg.getProcessor(ocio.FileTransform(src=lut, interpolation=ocio.INTERP_BEST))
                return ColorPipeline(key, to_lin, self._extract(proc, "ocio_disp", "ocd_"))
            if self.is_data(src):
                return ColorPipeline(key, _identity("ocio_lin"), _identity("ocio_disp"))
            p_lin = cfg.getProcessor(ocio.ColorSpaceTransform(src=src, dst=ocio.ROLE_SCENE_LINEAR))
            to_lin = _identity("ocio_lin") if p_lin.isNoOp() else self._extract(p_lin, "ocio_lin", "ocl_")
            p_disp = cfg.getProcessor(self._display_transform(display, view, look, lut, lut_mode))
            to_disp = self._extract(p_disp, "ocio_disp", "ocd_")
            return ColorPipeline(key, to_lin, to_disp)
        except Exception as exc:
            log.warning("OCIO pipeline %s failed: %s", key, exc)
            return self._fallback(key, src, str(exc))

    def cpu_function(self, src: str, display: str, view: str, look: str = "", lut: str = "",
                     lut_mode: str = "after"):
        """Callable mapping float32 (h, w, 3) input values to display values, for previews."""
        key = (self.uri, src, display, view, look, lut, lut_mode)
        if key in self._cpu:
            return self._cpu[key]
        fn = None
        if self.config:
            try:
                cfg = self.config
                if lut and lut_mode == "replace":
                    group = ocio.FileTransform(src=lut, interpolation=ocio.INTERP_BEST)
                elif self.is_data(src):
                    group = None
                else:
                    group = ocio.GroupTransform()
                    group.appendTransform(ocio.ColorSpaceTransform(src=src, dst=ocio.ROLE_SCENE_LINEAR))
                    group.appendTransform(self._display_transform(display, view, look, lut, lut_mode))
                cpu = cfg.getProcessor(group).getDefaultCPUProcessor() if group is not None else None
                fn = self._cpu_apply(cpu)
            except Exception as exc:
                log.debug("cpu processor failed: %s", exc)
                fn = None
        if fn is None:
            encoded = any(t in src.lower() for t in ("srgb", "encoded", "texture", "display", "rec.1886", "gamma"))
            fn = self._cpu_apply(None) if encoded else _srgb_encode_np
        self._cpu[key] = fn
        return fn

    @staticmethod
    def _cpu_apply(cpu):
        if cpu is None:
            return lambda rgb: rgb

        def fn(rgb: np.ndarray) -> np.ndarray:
            out = np.ascontiguousarray(rgb, np.float32).copy()
            cpu.applyRGB(out)
            return out

        return fn


def _srgb_encode_np(rgb: np.ndarray) -> np.ndarray:
    x = np.clip(rgb, 0, None)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
