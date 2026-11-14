import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import FlameField2D from "./FlameField2D.jsx";

/**
 * 3D volumetric flame view. The solver field stays strictly 2D ([ny][nx] K,
 * row 0 = physical bottom y = -H/2, buoyancy drifts toward +y); this view
 * revolves that half-plane about the flame axis (x = 0, through the ignition
 * center) and raymarches an emission-absorption fire shader through the
 * resulting axisymmetric volume. Disclosure: the axisymmetry is a
 * visualization assumption — the physics remains 2D.
 *
 * WebGL fallback: if a WebGL2 context cannot be created, delegates to the
 * 2D heatmap (FlameField2D) with a notice chip.
 */

const MAX_STEPS = 96.0;

const VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

const FRAG = /* glsl */ `
precision highp float;
varying vec2 vUv;
uniform sampler2D uData;   // temperature grid [ny][nx], row 0 = y = -H/2
uniform vec2  uSize;       // domain (L, H) meters
uniform float uAmbient;    // K
uniform float uPeak;       // K, per-run normalization ceiling
uniform vec3  uCamPos;
uniform mat4  uProjInv;
uniform mat4  uCamWorld;
uniform float uSteps;

// Axisymmetric sample: horizontal radius from the flame axis (x=z=0) picks
// the texture column on the right half-plane (x = +r); the left half of the
// 2D field is its mirror under the revolve assumption. u(x) = (x + L/2)/L.
float sampleT(vec3 p) {
  float r = length(p.xz);
  vec2 uv = vec2((r + 0.5 * uSize.x) / uSize.x, (p.y + 0.5 * uSize.y) / uSize.y);
  return texture2D(uData, clamp(uv, 0.0, 1.0)).r;
}

// Blackbody-ish fire ramp, consistent with the 2D heatmap palette.
vec3 fireRamp(float t) {
  t = clamp(t, 0.0, 1.0);
  vec3 c = mix(vec3(0.01, 0.01, 0.03), vec3(0.35, 0.02, 0.08), smoothstep(0.05, 0.30, t));
  c = mix(c, vec3(1.0, 0.25, 0.02), smoothstep(0.25, 0.55, t));
  c = mix(c, vec3(1.0, 0.65, 0.12), smoothstep(0.50, 0.75, t));
  c = mix(c, vec3(1.0, 0.95, 0.80), smoothstep(0.78, 1.00, t));
  return c;
}

// Slab-method ray/AABB hit for the revolved domain box.
vec2 boxHit(vec3 ro, vec3 rd) {
  vec3 inv = 1.0 / rd;
  vec3 b0 = vec3(-0.5 * uSize.x, -0.5 * uSize.y, -0.5 * uSize.x);
  vec3 b1 = vec3( 0.5 * uSize.x,  0.5 * uSize.y,  0.5 * uSize.x);
  vec3 t0 = (b0 - ro) * inv;
  vec3 t1 = (b1 - ro) * inv;
  vec3 tmin = min(t0, t1);
  vec3 tmax = max(t0, t1);
  return vec2(max(max(tmin.x, tmin.y), tmin.z), min(min(tmax.x, tmax.y), tmax.z));
}

void main() {
  // NDC point on the near plane -> camera-space ray -> world-space ray.
  vec2 ndc = vUv * 2.0 - 1.0;
  vec4 ph = uProjInv * vec4(ndc, -1.0, 1.0);
  vec3 dirCam = normalize(ph.xyz / ph.w);
  vec3 rd = normalize((uCamWorld * vec4(dirCam, 0.0)).xyz);
  vec3 ro = uCamPos;

  vec3 col = vec3(0.0);
  vec2 hit = boxHit(ro, rd);
  if (hit.y > max(hit.x, 0.0)) {
    float t0 = max(hit.x, 0.0);
    float span = hit.y - t0;
    float stepLen = span / uSteps;
    // Hash jitter to hide the layering banding between march steps.
    float jitter = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
    float trans = 1.0;
    for (int i = 0; i < 128; i++) {
      if (float(i) >= uSteps) break;
      vec3 p = ro + rd * (t0 + (float(i) + jitter) * stepLen);
      float temp = sampleT(p);
      float t01 = clamp((temp - uAmbient) / max(uPeak - uAmbient, 1.0), 0.0, 1.0);
      float heat = smoothstep(0.04, 0.42, t01);
      if (heat > 0.004) {
        vec3 em = fireRamp(t01) * (0.35 + 2.4 * t01 * t01);
        float a = 1.0 - exp(-28.0 * heat * stepLen);
        col += trans * a * em;
        trans *= (1.0 - a);
        if (trans < 0.02) break;
      }
    }
  }
  gl_FragColor = vec4(col, 1.0);
}
`;

function makeTex(nx, ny, ambientK) {
  const data = new Uint16Array(nx * ny);
  for (let i = 0; i < data.length; i++) {
    data[i] = THREE.DataUtils.toHalfFloat(ambientK);
  }
  const tex = new THREE.DataTexture(data, nx, ny, THREE.RedFormat, THREE.HalfFloatType);
  tex.minFilter = tex.magFilter = THREE.LinearFilter;
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.flipY = false; // row j = texel row j = physical y (-H/2 + j*dy)
  tex.colorSpace = THREE.NoColorSpace;
  tex.needsUpdate = true;
  return tex;
}

export default function FlameField3D({
  frame,
  time,
  frameIndex,
  frameCount,
  onScrub,
  gravityMode,
  finalData,
  domain,
  ambientK,
  headerExtra,
}) {
  const wrapRef = useRef(null);
  const glRef = useRef(null);
  const domainRef = useRef(domain);
  const ambientRef = useRef(ambientK);
  domainRef.current = domain;
  ambientRef.current = ambientK;
  const [glError, setGlError] = useState(null);

  // Scene setup (once): renderer, camera, orbit controls, raymarch quad,
  // domain wireframe + floor grid for spatial context.
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    let renderer;
    try {
      // preserveDrawingBuffer keeps the last frame readable for canvas
      // readback (screenshots + automated visual checks).
      renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    } catch (e) {
      setGlError(String(e));
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x05060a, 1);

    const scene = new THREE.Scene();
    const { L, H } = domainRef.current;
    const camera = new THREE.PerspectiveCamera(40, 1, 0.001, 10);
    camera.position.set(0.09, 0.05, 0.13);

    const controls = new OrbitControls(camera, wrap);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 0.04;
    controls.maxDistance = 0.8;

    const uniforms = {
      uData: { value: makeTex(1, 1, ambientRef.current) },
      uSize: { value: new THREE.Vector2(L, H) },
      uAmbient: { value: ambientRef.current },
      uPeak: { value: ambientRef.current + 400 },
      uCamPos: { value: new THREE.Vector3() },
      uProjInv: { value: new THREE.Matrix4() },
      uCamWorld: { value: new THREE.Matrix4() },
      uSteps: { value: MAX_STEPS },
    };

    const quadGeo = new THREE.PlaneGeometry(2, 2);
    const quadMat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms,
      depthTest: false,
      depthWrite: false,
    });
    const quad = new THREE.Mesh(quadGeo, quadMat);
    quad.frustumCulled = false;
    scene.add(quad);

    const grid = new THREE.GridHelper(L, 10, 0x3a4258, 0x232a3d);
    grid.position.y = -H / 2;
    grid.material.transparent = true;
    grid.material.opacity = 0.35;
    scene.add(grid);

    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(L, H, L)),
      new THREE.LineBasicMaterial({ color: 0x2a3247, transparent: true, opacity: 0.9 })
    );
    scene.add(edges);

    Object.assign(renderer.domElement.style, {
      position: "absolute",
      inset: "0",
      width: "100%",
      height: "100%",
      display: "block",
    });
    wrap.appendChild(renderer.domElement);

    glRef.current = { renderer, scene, camera, controls, uniforms, grid, edges, quadGeo, quadMat };

    const resize = () => {
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    resize();

    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      controls.update();
      camera.updateMatrixWorld();
      uniforms.uCamPos.value.copy(camera.position);
      uniforms.uProjInv.value.copy(camera.projectionMatrixInverse);
      uniforms.uCamWorld.value.copy(camera.matrixWorld);
      renderer.render(scene, camera);
    };
    loop();

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      quadGeo.dispose();
      quadMat.dispose();
      grid.geometry.dispose();
      grid.material.dispose();
      edges.geometry.dispose();
      edges.material.dispose();
      uniforms.uData.value.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      glRef.current = null;
    };
  }, []);

  // Domain changes (advanced panel): rebuild the wireframe + floor grid.
  useEffect(() => {
    const gl = glRef.current;
    if (!gl) return;
    const { L, H } = domain;
    gl.uniforms.uSize.value.set(L, H);
    gl.scene.remove(gl.grid);
    gl.scene.remove(gl.edges);
    gl.grid.geometry.dispose();
    gl.grid.material.dispose();
    gl.edges.geometry.dispose();
    gl.edges.material.dispose();
    gl.grid = new THREE.GridHelper(L, 10, 0x3a4258, 0x232a3d);
    gl.grid.position.y = -H / 2;
    gl.grid.material.transparent = true;
    gl.grid.material.opacity = 0.35;
    gl.edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(L, H, L)),
      new THREE.LineBasicMaterial({ color: 0x2a3247, transparent: true, opacity: 0.9 })
    );
    gl.scene.add(gl.grid);
    gl.scene.add(gl.edges);
  }, [domain.L, domain.H]);

  // Frame updates: flatten [ny][nx] K -> half-float texture + per-run
  // color normalization (same dynamic-range policy as the 2D heatmap).
  useEffect(() => {
    const gl = glRef.current;
    if (!gl || !frame || !frame.length || !frame[0]?.length) return;
    const ny = frame.length;
    const nx = frame[0].length;
    const { uniforms } = gl;
    const tex = uniforms.uData.value;
    if (tex.image.width !== nx || tex.image.height !== ny) {
      tex.dispose();
      uniforms.uData.value = makeTex(nx, ny, ambientK);
    }
    const dst = uniforms.uData.value;
    const data = dst.image.data;
    let maxT = 0;
    for (let j = 0; j < ny; j++) {
      const row = frame[j];
      const o = j * nx;
      for (let i = 0; i < nx; i++) {
        const v = row[i];
        if (v > maxT) maxT = v;
        data[o + i] = THREE.DataUtils.toHalfFloat(v);
      }
    }
    dst.needsUpdate = true;
    uniforms.uAmbient.value = ambientK;
    uniforms.uPeak.value = Math.max(Math.min(maxT, 3200), ambientK + 50);
  }, [frame, ambientK]);

  // WebGL unavailable -> delegate to the 2D heatmap with a notice.
  if (glError) {
    return (
      <FlameField2D
        frame={frame}
        time={time}
        frameIndex={frameIndex}
        frameCount={frameCount}
        onScrub={onScrub}
        gravityMode={gravityMode}
        finalData={finalData}
        headerExtra={
          <>
            {headerExtra}
            <span className="chip" title={`WebGL context failed: ${glError}`}>
              2D fallback (no WebGL)
            </span>
          </>
        }
      />
    );
  }

  const info = finalData ?? {};
  const modeLabel = {
    zero_g: "Zero-G — diffusion sphere",
    iss_micro_g: "ISS Micro-G — jitter",
    earth_1g: "Earth 1G — buoyant teardrop",
    mars_g: "Mars 0.38G — partial gravity",
    moon_g: "Moon 0.165G — partial gravity",
  }[gravityMode] ?? gravityMode;

  return (
    <div className="panel flame-panel">
      <div className="panel-head">
        <h2>Flame Field (3D)</h2>
        <span
          className="chip"
          title="The 2D solver field is revolved about the flame axis (axisymmetric assumption) for display; the physics stays strictly 2D."
        >
          axisymmetric revolve
        </span>
        <span className="chip">{modeLabel}</span>
        {time != null && (
          <span className="chip">t = {time.toFixed ? time.toFixed(3) : time} s</span>
        )}
        {headerExtra}
      </div>
      <div className="flame-canvas-wrap gl-wrap" ref={wrapRef}>
        {!frame && <div className="flame-placeholder">Waiting for solver frames…</div>}
      </div>
      <div className="flame-hint muted small">
        drag = orbit · wheel = zoom · right-drag = pan
      </div>
      <div className="scrubber-row">
        <input
          type="range"
          min={0}
          max={Math.max(frameCount - 1, 0)}
          value={Math.min(frameIndex, Math.max(frameCount - 1, 0))}
          onChange={(e) => onScrub(parseInt(e.target.value, 10))}
          aria-label="Time scrubber"
        />
        <span className="muted small">
          frame {frameIndex + 1}/{frameCount}
        </span>
      </div>
      {info && (
        <div className="final-stats">
          <Stat label="Peak T" value={`${Math.round(info.peak_temp_k ?? 0)} K`} />
          <Stat
            label="Max radius"
            value={`${((info.max_flame_radius_m ?? 0) * 1000).toFixed(1)} mm`}
          />
          <Stat label="Quenched" value={info.quenched ? "yes" : "no"} warn={info.quenched} />
          <Stat label="Stability" value={`${(info.stability ?? 0).toFixed(0)}/100`} />
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, warn }) {
  return (
    <div className={`stat ${warn ? "warn" : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}