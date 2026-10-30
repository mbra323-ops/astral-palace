"""GLSL 3.30 sources. Everything renders additively into an RGBA16F HDR target,
then goes through a mip-chain bloom and a filmic tonemap."""

HEADER = "#version 330 core\n"

# Node positions live in textures so stars, lines and dust can all fetch them
# by note index; "from" and "to" rows let layout changes glide into place.
NODE_FETCH = """
uniform sampler2D uPosFrom;
uniform sampler2D uPosTo;
uniform sampler2D uHighlight;
uniform float uMix;
const int TEXW = 1024;
ivec2 nodeCoord(int i) { return ivec2(i % TEXW, i / TEXW); }
vec4 nodePos(int i) {
    ivec2 c = nodeCoord(i);
    return mix(texelFetch(uPosFrom, c, 0), texelFetch(uPosTo, c, 0), uMix);
}
vec2 nodeHighlight(int i) { return texelFetch(uHighlight, nodeCoord(i), 0).rg; }
float nodeMatch(int i) { return texelFetch(uHighlight, nodeCoord(i), 0).b; }
"""

COMMON = """
uniform mat4 uModel;
uniform mat4 uViewProj;
uniform vec3 uCamPos;
uniform vec2 uViewport;
uniform float uPxScale;   // device px per reference px (4K height = 1.0)
uniform float uRefDist;
uniform float uTime;
uniform float uSearchDim;  // 0..1 while searching: non-matching stars fade back
"""

STAR_VS = HEADER + NODE_FETCH + COMMON + """
layout(location = 0) in vec4 aColor;   // rgb, brightness
layout(location = 1) in vec4 aMeta;    // size, spikes, seed, archive
out vec3 vColor;
out float vIntensity;
out float vSigma;
out float vSize;
out float vSpike;
out float vHalo;
void main() {
    int id = gl_VertexID;
    vec4 p = nodePos(id);
    vec2 hl = nodeHighlight(id);
    vec4 world = uModel * vec4(p.xyz, 1.0);
    gl_Position = uViewProj * world;
    float persp = clamp(uRefDist / distance(world.xyz, uCamPos), 0.5, 2.5);

    float seed = aMeta.z;
    float twinkle = 1.0 + 0.05 * sin(uTime * (0.35 + seed * 0.5) + seed * 61.0);
    float boost = 1.0 + 3.0 * hl.r + 0.9 * hl.g;
    float match = nodeMatch(id);
    boost *= mix(1.0, mix(0.18, 2.4, match), uSearchDim);

    float sigma = (0.75 + 1.25 * aMeta.x) * uPxScale * persp
                * (1.0 + 0.35 * hl.r) * (1.0 + 0.4 * match * uSearchDim);
    float sClamped = max(sigma, 0.85);
    // keep total energy when tiny stars are clamped to a minimum footprint
    float energy = (sigma * sigma) / (sClamped * sClamped);

    vSigma = sClamped;
    vIntensity = aColor.a * p.w * twinkle * boost * energy;
    vColor = aColor.rgb;
    vSpike = aMeta.y * (1.0 + hl.r);
    vHalo = mix(1.0, 0.45, aMeta.w);
    vSize = min(sClamped * (vSpike > 0.0 ? 34.0 : 18.0) + 2.0, 256.0);
    gl_PointSize = vSize;
}
"""

STAR_FS = HEADER + """
in vec3 vColor;
in float vIntensity;
in float vSigma;
in float vSize;
in float vSpike;
in float vHalo;
out vec4 frag;
void main() {
    vec2 q = (gl_PointCoord - 0.5) * vSize;
    float d2 = dot(q, q);
    float d = sqrt(d2);
    float edge = 1.0 - smoothstep(0.32 * vSize, 0.5 * vSize, d);

    float core = exp(-d2 / (2.0 * vSigma * vSigma));
    float halo = 0.055 * vHalo * exp(-d / (vSigma * 2.2)) * edge;
    float spike = 0.0;
    if (vSpike > 0.0) {
        float w = 0.55;
        float len = vSigma * 7.0;
        spike = exp(-abs(q.y) / w) * exp(-abs(q.x) / len)
              + exp(-abs(q.x) / w) * exp(-abs(q.y) / len);
        spike *= 0.22 * vSpike * edge;
    }
    // white-hot centre, coloured falloff
    vec3 c = mix(vColor, vec3(1.0, 0.97, 0.92), clamp(core * vIntensity * 0.35, 0.0, 0.85));
    vec3 col = (c * core * 3.0 + vColor * (halo + spike)) * vIntensity;
    frag = vec4(col, 1.0);
}
"""

LINE_VS = HEADER + NODE_FETCH + COMMON + """
layout(location = 0) in vec2 aEdge;     // node a, node b (per instance)
layout(location = 1) in float aWeight;  // per instance
uniform float uLineWidth;
noperspective out float vAcross;
noperspective out float vAlong;
flat out float vLen;
flat out float vHalfW;
flat out float vIntensity;
flat out float vHover;
flat out float vFromB;
void main() {
    int ia = int(aEdge.x + 0.5);
    int ib = int(aEdge.y + 0.5);
    vec4 pa = nodePos(ia);
    vec4 pb = nodePos(ib);
    vec4 ca = uViewProj * (uModel * vec4(pa.xyz, 1.0));
    vec4 cb = uViewProj * (uModel * vec4(pb.xyz, 1.0));
    if (ca.w < 0.05 || cb.w < 0.05) {
        // an end is behind the camera (zoomed right in): drop the line
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        return;
    }
    vec2 sa = (ca.xy / ca.w * 0.5 + 0.5) * uViewport;
    vec2 sb = (cb.xy / cb.w * 0.5 + 0.5) * uViewport;

    float ha = nodeHighlight(ia).r;
    float hb = nodeHighlight(ib).r;
    float h = max(ha, hb);

    vec2 dv = sb - sa;
    float len = max(length(dv), 1e-3);
    vec2 dir = dv / len;
    vec2 nrm = vec2(-dir.y, dir.x);
    float halfw = uLineWidth * uPxScale * (0.5 + 0.4 * h);

    int corner = gl_VertexID;   // triangle strip 0..3
    float s = float(corner >> 1);
    float side = float(corner & 1) * 2.0 - 1.0;
    float pad = halfw + 1.0;
    vec2 px = mix(sa, sb, s) + nrm * side * pad + dir * (s * 2.0 - 1.0);
    float w = mix(ca.w, cb.w, s);
    float z = mix(ca.z / ca.w, cb.z / cb.w, s);
    gl_Position = vec4((px / uViewport * 2.0 - 1.0) * w, z * w, w);

    float worldLen = distance(pa.xyz, pb.xyz);
    float fade = mix(1.0, 0.15, smoothstep(0.08, 0.9, worldLen));
    vAcross = side * pad;
    vAlong = s * len;
    vLen = len;
    vHalfW = halfw;
    vIntensity = aWeight * fade * min(pa.w, pb.w);
    float m = max(nodeMatch(ia), nodeMatch(ib));
    vIntensity *= mix(mix(1.0, mix(0.2, 1.3, m), uSearchDim), 1.0, h);
    vHover = h;
    vFromB = hb > ha ? 1.0 : 0.0;
}
"""

LINE_FS = HEADER + """
uniform float uLineBase;
uniform float uLineHover;
uniform vec3 uLineColor;
uniform vec3 uLineHoverColor;
uniform float uPxScale;
uniform float uTime;
noperspective in float vAcross;
noperspective in float vAlong;
flat in float vLen;
flat in float vHalfW;
flat in float vIntensity;
flat in float vHover;
flat in float vFromB;
out vec4 frag;
void main() {
    float cov = 1.0 - smoothstep(vHalfW - 0.5, vHalfW + 0.5, abs(vAcross));
    // constellation-chart gaps so lines never touch the stars
    float gap = 7.0 * uPxScale;
    float ramp = 10.0 * uPxScale;
    cov *= smoothstep(gap, gap + ramp, vAlong) * smoothstep(gap, gap + ramp, vLen - vAlong);

    float along = vFromB > 0.5 ? (vLen - vAlong) : vAlong;
    float pulse = exp(-pow((fract(along / (420.0 * uPxScale) - uTime * 0.35) - 0.5) * 9.0, 2.0));
    float hover = vHover * (uLineHover + 0.5 * uLineHover * pulse);
    vec3 col = uLineColor * uLineBase * (1.0 - vHover) + uLineHoverColor * hover;
    frag = vec4(col * vIntensity * cov, 1.0);
}
"""

DUST_VS = HEADER + NODE_FETCH + COMMON + """
layout(location = 0) in vec4 aPos;    // bound: offset xyz, node | free: r, theta, z, -1
layout(location = 1) in vec4 aColor;  // rgb, intensity
layout(location = 2) in float aSize;
uniform float uDiff;
out vec3 vColor;
out float vSigma;
out float vSize;
void main() {
    vec3 p;
    float alpha = 1.0;
    if (aPos.w >= 0.0) {
        vec4 n = nodePos(int(aPos.w + 0.5));
        p = n.xyz + aPos.xyz;
        alpha = n.w;
    } else {
        float r = aPos.x;
        // differential (Keplerian-ish) drift on top of the rigid spin
        float th = aPos.y + uDiff * uTime * pow(r + 0.25, -1.5);
        p = vec3(r * cos(th), r * sin(th), aPos.z);
        alpha = uMix;
    }
    vec4 world = uModel * vec4(p, 1.0);
    gl_Position = uViewProj * world;
    float persp = clamp(uRefDist / distance(world.xyz, uCamPos), 0.5, 2.5);
    float sigma = aSize * uPxScale * persp;
    float sc = max(sigma, 0.7);
    vSigma = sc;
    vColor = aColor.rgb * aColor.a * alpha * (sigma * sigma) / (sc * sc);
    vSize = sc * 6.0 + 1.0;
    gl_PointSize = vSize;
}
"""

DUST_FS = HEADER + """
in vec3 vColor;
in float vSigma;
in float vSize;
out vec4 frag;
void main() {
    vec2 q = (gl_PointCoord - 0.5) * vSize;
    float g = exp(-dot(q, q) / (2.0 * vSigma * vSigma));
    frag = vec4(vColor * g, 1.0);
}
"""

SKY_VS = HEADER + """
layout(location = 0) in vec3 aDir;
layout(location = 1) in vec4 aColor;
uniform mat4 uSkyViewProj;
uniform float uPxScale;
out vec3 vColor;
out float vSize;
void main() {
    gl_Position = uSkyViewProj * vec4(aDir * 500.0, 1.0);
    float sigma = max(0.55 * uPxScale, 0.7);
    vSize = sigma * 6.0;
    vColor = aColor.rgb * aColor.a;
    gl_PointSize = vSize;
}
"""

SKY_FS = HEADER + """
in vec3 vColor;
in float vSize;
out vec4 frag;
void main() {
    vec2 q = (gl_PointCoord - 0.5) * vSize;
    float s = vSize / 6.0;
    frag = vec4(vColor * exp(-dot(q, q) / (2.0 * s * s)), 1.0);
}
"""

FULLSCREEN_VS = HEADER + """
out vec2 vUV;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    vUV = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

# 13-tap downsample (Jimenez, CoD:AW) with Karis average on the first pass
DOWN_FS = HEADER + """
uniform sampler2D uSrc;
uniform vec2 uTexel;
uniform int uKaris;
in vec2 vUV;
out vec4 frag;
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
vec3 kw(vec3 c) { return c / (1.0 + luma(c)); }
void main() {
    vec2 t = uTexel;
    vec3 a = texture(uSrc, vUV + t * vec2(-2,  2)).rgb;
    vec3 b = texture(uSrc, vUV + t * vec2( 0,  2)).rgb;
    vec3 c = texture(uSrc, vUV + t * vec2( 2,  2)).rgb;
    vec3 d = texture(uSrc, vUV + t * vec2(-2,  0)).rgb;
    vec3 e = texture(uSrc, vUV).rgb;
    vec3 f = texture(uSrc, vUV + t * vec2( 2,  0)).rgb;
    vec3 g = texture(uSrc, vUV + t * vec2(-2, -2)).rgb;
    vec3 h = texture(uSrc, vUV + t * vec2( 0, -2)).rgb;
    vec3 i = texture(uSrc, vUV + t * vec2( 2, -2)).rgb;
    vec3 j = texture(uSrc, vUV + t * vec2(-1,  1)).rgb;
    vec3 k = texture(uSrc, vUV + t * vec2( 1,  1)).rgb;
    vec3 l = texture(uSrc, vUV + t * vec2(-1, -1)).rgb;
    vec3 m = texture(uSrc, vUV + t * vec2( 1, -1)).rgb;
    vec3 o;
    if (uKaris == 1) {
        vec3 g0 = (a + b + d + e) * 0.25, g1 = (b + c + e + f) * 0.25;
        vec3 g2 = (d + e + g + h) * 0.25, g3 = (e + f + h + i) * 0.25;
        vec3 g4 = (j + k + l + m) * 0.25;
        o = kw(g0) * 0.125 + kw(g1) * 0.125 + kw(g2) * 0.125 + kw(g3) * 0.125 + kw(g4) * 0.5;
        o = o / max(1.0 - luma(o), 1e-4);
    } else {
        o = e * 0.125 + (a + c + g + i) * 0.03125 + (b + d + f + h) * 0.0625 + (j + k + l + m) * 0.125;
    }
    frag = vec4(max(o, 0.0), 1.0);
}
"""

UP_FS = HEADER + """
uniform sampler2D uSrc;
uniform vec2 uTexel;
uniform float uRadius;
uniform float uWeight;
in vec2 vUV;
out vec4 frag;
void main() {
    vec2 t = uTexel * uRadius;
    vec3 s = texture(uSrc, vUV).rgb * 4.0;
    s += (texture(uSrc, vUV + vec2(-t.x, 0)).rgb + texture(uSrc, vUV + vec2(t.x, 0)).rgb
        + texture(uSrc, vUV + vec2(0, -t.y)).rgb + texture(uSrc, vUV + vec2(0, t.y)).rgb) * 2.0;
    s += texture(uSrc, vUV + vec2(-t.x, -t.y)).rgb + texture(uSrc, vUV + vec2(t.x, -t.y)).rgb
       + texture(uSrc, vUV + vec2(-t.x, t.y)).rgb + texture(uSrc, vUV + vec2(t.x, t.y)).rgb;
    frag = vec4(s / 16.0 * uWeight, 1.0);
}
"""

COMPOSITE_FS = HEADER + """
uniform sampler2D uHdr;
uniform sampler2D uBloom;
uniform float uBloomStrength;
uniform float uExposure;
uniform float uTime;
uniform vec2 uViewport;
uniform vec2 uScreenOrigin;   // this monitor's offset within the whole desktop (px)
uniform vec2 uScreenTotal;    // whole desktop size (px)
uniform vec2 uUVScale;        // output -> overscanned HDR mapping
uniform vec2 uUVOffset;
uniform sampler2D uBg;       // deep-sky layer, rendered at low resolution
in vec2 vUV;
out vec4 frag;

// ACES (Stephen Hill fit): warm highlights roll through gold to white
const mat3 ACESIn = mat3(0.59719, 0.07600, 0.02840, 0.35458, 0.90834, 0.13383, 0.04823, 0.01566, 0.83777);
const mat3 ACESOut = mat3(1.60475, -0.10208, -0.00327, -0.53108, 1.10813, -0.07276, -0.07367, -0.00605, 1.07602);
vec3 rrtOdt(vec3 v) {
    vec3 a = v * (v + 0.0245786) - 0.000090537;
    vec3 b = v * (0.983729 * v + 0.4329510) + 0.238081;
    return a / b;
}
vec3 aces(vec3 c) { return clamp(ACESOut * rrtOdt(ACESIn * c), 0.0, 1.0); }
vec3 toSrgb(vec3 c) {
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}
float hash(vec2 p) {
    p = fract(p * vec2(443.897, 441.423));
    p += dot(p, p.yx + 19.19);
    return fract((p.x + p.y) * p.x);
}
void main() {
    vec2 uv = vUV * uUVScale + uUVOffset;
    vec3 hdr = texture(uHdr, uv).rgb;
    vec3 bloom = texture(uBloom, uv).rgb;
    // gentle vignette across the whole desktop, not per monitor
    vec2 g = (uScreenOrigin + vUV * uViewport) / uScreenTotal;
    g.y = 1.0 - g.y;
    vec3 c = (hdr + bloom * uBloomStrength + texture(uBg, uv).rgb) * uExposure;
    vec2 v = (g - 0.5) * vec2(1.0, 1.6);
    c *= mix(1.0, 0.82, smoothstep(0.3, 0.9, length(v)));

    c = toSrgb(aces(c));
    // triangular dither kills banding in the dark gradients
    vec2 px = gl_FragCoord.xy + fract(uTime * 7.31) * 113.0;
    float n = hash(px) + hash(px + 71.3) - 1.0;
    c += n / 255.0;
    frag = vec4(c, 1.0);
}
"""

BLIT_FS = HEADER + """
uniform sampler2D uSrc;
in vec2 vUV;
out vec4 frag;
void main() { frag = vec4(texture(uSrc, vUV).rgb, 1.0); }
"""

# Smooth and low-frequency, so it renders at 1/8 resolution and is upsampled.
BG_FS = HEADER + """
uniform vec2 uScreenTotal;    // whole desktop size (px)
uniform vec2 uExtOrigin;      // overscanned frame's top-left within the desktop (px)
uniform vec2 uExtSize;        // overscanned frame size (px)
""" + """uniform mat4 uInvSky;         // overscanned NDC -> sky direction
uniform vec2 uGalaxyCenter;   // galaxy centre as a fraction of the whole desktop
uniform float uBgGlow;
uniform float uBgNebula;
""" + """
in vec2 vUV;
out vec4 frag;
float hash3(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float vnoise(vec3 x) {
    vec3 i = floor(x), f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash3(i), hash3(i + vec3(1,0,0)), f.x),
                   mix(hash3(i + vec3(0,1,0)), hash3(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash3(i + vec3(0,0,1)), hash3(i + vec3(1,0,1)), f.x),
                   mix(hash3(i + vec3(0,1,1)), hash3(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float fbm(vec3 p) {
    float a = 0.5, s = 0.0;
    for (int k = 0; k < 5; k++) { s += a * vnoise(p); p = p * 2.03 + 11.7; a *= 0.5; }
    return s;
}

// deep sky: faint light that never quite reaches black, plus dusk-blue wisps
vec3 background(vec2 uv, vec2 g) {
    vec4 w = uInvSky * vec4(uv * 2.0 - 1.0, 1.0, 1.0);
    vec3 dir = normalize(w.xyz / w.w);

    // broad glow around the galaxy: warm close in, cooling to dusk blue
    vec2 d = (g - uGalaxyCenter) * vec2(uScreenTotal.x / uScreenTotal.y, 1.0);
    float r = length(d * vec2(0.55, 1.0));
    vec3 warm = vec3(0.045, 0.024, 0.012) * exp(-r * 2.0);
    vec3 cool = vec3(0.016, 0.022, 0.048) * exp(-r * 0.42);
    vec3 glow = (warm + cool) * uBgGlow;

    // wispy clouds in the sky sphere
    float n = fbm(dir * 2.4 + vec3(3.1, 0.0, 1.7));
    float m = fbm(dir * 6.0 - vec3(1.3, 4.2, 0.0));
    float cloud = smoothstep(0.48, 0.85, n) * (0.55 + 0.45 * m);
    float hue = fbm(dir * 1.1 + 9.0);
    vec3 tint = mix(vec3(0.16, 0.24, 0.55), vec3(0.32, 0.18, 0.50), smoothstep(0.35, 0.65, hue));
    vec3 neb = tint * cloud * 0.07 * uBgNebula;
    return glow + neb;
}

void main() {
    vec2 g = (uExtOrigin + vec2(vUV.x, 1.0 - vUV.y) * uExtSize) / uScreenTotal;
    g.y = 1.0 - g.y;
    frag = vec4(background(vUV, g), 1.0);
}
"""
