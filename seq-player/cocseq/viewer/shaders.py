"""GLSL sources for the two render passes.

Pass 1 (per clip): source pixels -> input color space -> scene linear -> grading ->
display transform -> display grading, rendered at image resolution into a float texture.
Pass 2 (per widget): place the pass-1 textures on screen (zoom, compare modes,
environment maps) over the background.
"""

VERTEX = """#version 330 core
layout(location = 0) in vec2 a_pos;
out vec2 v_uv;
void main() {
    v_uv = a_pos * 0.5 + 0.5;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

COLOR_FRAGMENT = """#version 330 core
in vec2 v_uv;
out vec4 fragColor;

uniform sampler2D u_src;
uniform int u_nch;
uniform int u_channel;       // 0 rgb, 1 r, 2 g, 3 b, 4 alpha, 5 luminance
uniform int u_video_levels;  // 1: expand legal range
uniform int u_unpremult;
uniform float u_gain;
uniform float u_offset;
uniform float u_contrast;
uniform float u_saturation;
uniform mat3 u_hue;
uniform float u_softclip;
uniform float u_gamma;
uniform int u_levels;
uniform float u_in_lo;
uniform float u_in_hi;
uniform float u_lv_gamma;
uniform float u_out_lo;
uniform float u_out_hi;
uniform int u_invert;

//__OCIO_LIN__

//__OCIO_DISP__

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

void main() {
    vec4 c = texture(u_src, v_uv);
    if (u_nch == 1) c = vec4(c.rrr, 1.0);
    else if (u_nch == 2) c = vec4(c.rrr, c.g);
    else if (u_nch == 3) c.a = 1.0;
    if (u_video_levels == 1) c.rgb = (c.rgb - 16.0 / 255.0) * (255.0 / 219.0);
    if (u_channel == 4) { fragColor = vec4(c.aaa, 1.0); return; }
    float a = c.a;
    vec3 rgb = c.rgb;
    if (u_unpremult == 1 && a > 1e-6) rgb /= a;

    vec3 lin = ocio_lin(vec4(rgb, 1.0)).rgb;
    lin = lin * u_gain + vec3(u_offset);
    if (u_contrast != 1.0) lin = sign(lin) * 0.18 * pow(abs(lin) / 0.18, vec3(u_contrast));
    if (u_saturation != 1.0) lin = mix(vec3(luma(lin)), lin, u_saturation);
    lin = u_hue * lin;
    if (u_softclip > 0.0) {
        float t = 1.0 - u_softclip;
        vec3 over = max(lin - vec3(t), vec3(0.0));
        lin = min(lin, vec3(t)) + u_softclip * (vec3(1.0) - exp(-over / u_softclip));
    }
    if (u_channel == 1) lin = vec3(lin.r);
    else if (u_channel == 2) lin = vec3(lin.g);
    else if (u_channel == 3) lin = vec3(lin.b);
    else if (u_channel == 5) lin = vec3(luma(lin));

    vec3 d = ocio_disp(vec4(lin, 1.0)).rgb;
    if (u_gamma != 1.0) d = sign(d) * pow(abs(d), vec3(1.0 / u_gamma));
    if (u_levels == 1) {
        d = clamp((d - vec3(u_in_lo)) / max(u_in_hi - u_in_lo, 1e-5), 0.0, 1.0);
        d = pow(d, vec3(1.0 / max(u_lv_gamma, 1e-3)));
        d = mix(vec3(u_out_lo), vec3(u_out_hi), d);
    }
    if (u_invert == 1) d = vec3(1.0) - d;
    if (u_unpremult == 1) d *= a;
    fragColor = vec4(d, a);
}
"""

COMPOSITE_FRAGMENT = """#version 330 core
out vec4 fragColor;

uniform sampler2D u_img0;
uniform sampler2D u_img1;
uniform sampler2D u_img2;
uniform sampler2D u_img3;
uniform int u_count;
uniform int u_valid[4];
uniform vec4 u_rect[4];      // data window in canvas coordinates: x0, y0, x1, y1
uniform vec4 u_disp[4];      // display window in canvas coordinates
uniform mat3 u_inv;          // device pixel (origin top left) -> canvas
uniform float u_fbh;
uniform float u_dpr;
uniform int u_mode;          // 0 single, 1 wipe, 2 overlay, 3 difference, 4.. side by side / tiles
uniform vec2 u_wipe_p;
uniform vec2 u_wipe_n;
uniform float u_overlay;
uniform float u_diff_gain;
uniform int u_alpha_mode;    // 0 ignore, 1 straight, 2 premultiplied
uniform int u_bg;            // 0 solid, 1 checker
uniform vec3 u_bg_a;
uniform vec3 u_bg_b;
uniform float u_checker;
uniform vec3 u_surround;
uniform int u_mirror_x;
uniform int u_mirror_y;
uniform int u_env;
uniform mat3 u_env_rot;
uniform float u_env_tan;
uniform vec2 u_view;
uniform int u_nearest;

const float PI = 3.14159265358979;

vec4 fetch(int i, vec2 uv, vec2 gx, vec2 gy) {
    if (i == 0) return textureGrad(u_img0, uv, gx, gy);
    if (i == 1) return textureGrad(u_img1, uv, gx, gy);
    if (i == 2) return textureGrad(u_img2, uv, gx, gy);
    return textureGrad(u_img3, uv, gx, gy);
}

vec2 mirror(int i, vec2 p) {
    vec4 d = u_disp[i];
    if (u_mirror_x == 1) p.x = d.x + d.z - p.x;
    if (u_mirror_y == 1) p.y = d.y + d.w - p.y;
    return p;
}

// Sample slot i at canvas point p. Returns alpha 0 and inside=false outside its data window.
vec4 slot(int i, vec2 p, vec2 dpx, vec2 dpy, out float inside) {
    inside = 0.0;
    if (i >= u_count || u_valid[i] == 0) return vec4(0.0);
    vec2 q = mirror(i, p);
    vec4 r = u_rect[i];
    vec2 size = r.zw - r.xy;
    vec2 uv = (q - r.xy) / size;
    if (uv.x < 0.0 || uv.y < 0.0 || uv.x >= 1.0 || uv.y >= 1.0) return vec4(0.0);
    inside = 1.0;
    vec2 gx = dpx / size;
    vec2 gy = dpy / size;
    if (u_mirror_x == 1) { gx.x = -gx.x; gy.x = -gy.x; }
    if (u_mirror_y == 1) { gx.y = -gx.y; gy.y = -gy.y; }
    return fetch(i, uv, gx, gy);
}

bool in_disp(int i, vec2 p) {
    vec4 d = u_disp[i];
    return p.x >= d.x && p.y >= d.y && p.x < d.z && p.y < d.w;
}

void main() {
    vec2 w = vec2(gl_FragCoord.x, u_fbh - gl_FragCoord.y);
    vec3 bg = u_bg_a;
    if (u_bg == 1) {
        vec2 cell = floor(w / (u_checker * u_dpr));
        bg = mod(cell.x + cell.y, 2.0) < 0.5 ? u_bg_a : u_bg_b;
    }
    vec4 col = vec4(0.0);
    float cover = 0.0;
    bool on_image = false;

    if (u_env == 1) {
        vec2 ndc = (w - 0.5 * u_view) / (0.5 * u_view.y);
        vec3 dir = normalize(u_env_rot * vec3(ndc.x * u_env_tan, -ndc.y * u_env_tan, 1.0));
        float lon = atan(dir.x, dir.z);
        float lat = asin(clamp(dir.y, -1.0, 1.0));
        vec2 uv = vec2(lon / (2.0 * PI) + 0.5, 0.5 - lat / PI);
        col = textureLod(u_img0, uv, 0.0);
        cover = 1.0;
        on_image = true;
    } else {
        vec2 p = (u_inv * vec3(w, 1.0)).xy;
        vec2 dpx = (u_inv * vec3(1.0, 0.0, 0.0)).xy;
        vec2 dpy = (u_inv * vec3(0.0, 1.0, 0.0)).xy;
        if (u_nearest == 1) { dpx = vec2(0.0); dpy = vec2(0.0); }
        float ia, ib;
        if (u_mode == 0) {
            col = slot(0, p, dpx, dpy, ia);
            cover = ia;
            on_image = in_disp(0, p) || ia > 0.0;
        } else if (u_mode == 1) {
            float s = dot(p - u_wipe_p, u_wipe_n);
            if (s < 0.0) { col = slot(0, p, dpx, dpy, ia); cover = ia; }
            else { col = slot(1, p, dpx, dpy, ib); cover = ib; }
            on_image = in_disp(0, p) || cover > 0.0;
        } else if (u_mode == 2) {
            vec4 a = slot(0, p, dpx, dpy, ia);
            vec4 b = slot(1, p, dpx, dpy, ib);
            float k = u_overlay * ib;
            col = mix(a, b, k);
            cover = max(ia, ib);
            on_image = in_disp(0, p) || cover > 0.0;
        } else if (u_mode == 3) {
            vec4 a = slot(0, p, dpx, dpy, ia);
            vec4 b = slot(1, p, dpx, dpy, ib);
            col = vec4(abs(a.rgb - b.rgb) * u_diff_gain, max(a.a, b.a));
            cover = max(ia, ib);
            on_image = in_disp(0, p) || cover > 0.0;
        } else {
            for (int i = 0; i < 4; ++i) {
                if (i >= u_count) break;
                float inside;
                vec4 v = slot(i, p, dpx, dpy, inside);
                if (inside > 0.0) { col = v; cover = 1.0; on_image = true; break; }
                if (in_disp(i, p)) on_image = true;
            }
        }
    }

    vec3 base = on_image ? bg : u_surround;
    vec3 outc;
    if (u_alpha_mode == 1) outc = mix(base, col.rgb, clamp(col.a, 0.0, 1.0) * cover);
    else if (u_alpha_mode == 2) outc = col.rgb * cover + base * (1.0 - clamp(col.a, 0.0, 1.0) * cover);
    else outc = mix(base, col.rgb, cover);
    fragColor = vec4(clamp(outc, 0.0, 1.0), 1.0);
}
"""


def color_program_source(to_lin_text: str, to_disp_text: str) -> str:
    return COLOR_FRAGMENT.replace("//__OCIO_LIN__", to_lin_text).replace("//__OCIO_DISP__", to_disp_text)
