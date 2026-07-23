import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import * as THREE from "three";
import type { DockingAtom, DockingBond, DockingPose } from "../api/types";
import { tw } from "../design_system";
import { translateMetric } from "../translator";
import { GlassPanel } from "./GlassPanel";
import { MetricTooltip } from "./MetricTooltip";
import { CollapsibleTelemetry } from "./CollapsibleTelemetry";

export type DockingViewportProps = {
  pose: DockingPose | null;
};

const ELEMENT_COLOR: Record<string, number> = {
  C: 0x94a3b8,
  N: 0x38bdf8,
  O: 0xfb7185,
  H: 0xe2e8f0,
  S: 0xfbbf24,
  P: 0xf472b6,
};

const ELEMENT_RADIUS: Record<string, number> = {
  C: 0.38,
  N: 0.36,
  O: 0.34,
  H: 0.18,
  S: 0.42,
  P: 0.4,
};

function atomColor(el: string, role: DockingAtom["role"]): number {
  if (role === "ligand" && el === "C") return 0x00e5ff;
  return ELEMENT_COLOR[el] ?? 0xa3e635;
}

function buildDefaultScene(pose: DockingPose): { atoms: DockingAtom[]; bonds: DockingBond[] } {
  if (pose.atoms?.length) {
    return { atoms: pose.atoms, bonds: pose.bonds ?? [] };
  }
  // Fallback demo pocket matching voidsignal.docking.make_demo_receptor_ligand
  const atoms: DockingAtom[] = [
    { serial: 1, name: "N1", element: "N", x: 3, y: 0, z: 0, role: "receptor" },
    { serial: 2, name: "O1", element: "O", x: 0, y: 3, z: 0, role: "receptor" },
    { serial: 3, name: "O2", element: "O", x: -3, y: 0, z: 0, role: "receptor" },
    { serial: 4, name: "N2", element: "N", x: 0, y: -3, z: 0, role: "receptor" },
    { serial: 5, name: "C1", element: "C", x: 2.2, y: 2.2, z: 0.5, role: "receptor" },
    { serial: 6, name: "C2", element: "C", x: -2.2, y: 2.2, z: -0.5, role: "receptor" },
    { serial: 7, name: "C3", element: "C", x: -2.2, y: -2.2, z: 0.4, role: "receptor" },
    { serial: 8, name: "C4", element: "C", x: 2.2, y: -2.2, z: -0.4, role: "receptor" },
    { serial: 101, name: "C1", element: "C", x: 0, y: 0, z: 0, role: "ligand" },
    { serial: 102, name: "N1", element: "N", x: 0, y: 1.35, z: 0, role: "ligand" },
    { serial: 103, name: "H1", element: "H", x: 0, y: 2.15, z: 0, role: "ligand" },
    { serial: 104, name: "O1", element: "O", x: 1.35, y: 0, z: 0, role: "ligand" },
    { serial: 105, name: "C2", element: "C", x: -1.2, y: -0.3, z: 0.2, role: "ligand" },
  ];
  const bonds: DockingBond[] = [
    { a: 101, b: 102, role: "ligand" },
    { a: 102, b: 103, role: "ligand" },
    { a: 101, b: 104, role: "ligand" },
    { a: 101, b: 105, role: "ligand" },
    { a: 5, b: 1, role: "receptor" },
    { a: 5, b: 2, role: "receptor" },
    { a: 6, b: 2, role: "receptor" },
    { a: 6, b: 3, role: "receptor" },
    { a: 7, b: 3, role: "receptor" },
    { a: 7, b: 4, role: "receptor" },
    { a: 8, b: 4, role: "receptor" },
    { a: 8, b: 1, role: "receptor" },
    { a: 103, b: 2, role: "hbond" },
    { a: 104, b: 1, role: "hbond" },
  ];
  return { atoms, bonds };
}

function makeBondMesh(
  a: THREE.Vector3,
  b: THREE.Vector3,
  color: number,
  radius: number,
  dashed = false,
): THREE.Object3D {
  const dir = new THREE.Vector3().subVectors(b, a);
  const len = dir.length();
  if (len < 1e-6) return new THREE.Group();
  if (dashed) {
    const geo = new THREE.BufferGeometry().setFromPoints([a, b]);
    const mat = new THREE.LineDashedMaterial({
      color,
      dashSize: 0.25,
      gapSize: 0.15,
      linewidth: 1,
    });
    const line = new THREE.Line(geo, mat);
    line.computeLineDistances();
    return line;
  }
  const geo = new THREE.CylinderGeometry(radius, radius, len, 8);
  const mat = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.45,
    metalness: 0.15,
    transparent: true,
    opacity: 0.92,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.position.copy(a).add(b).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  return mesh;
}

/**
 * Interactive Three.js pocket viewer — real WebGL docking scene (orbit + drag).
 */
export function DockingViewport({ pose }: DockingViewportProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const dg = pose ? translateMetric("DG", pose.deltaG) : null;
  const ki = pose ? translateMetric("KI", pose.ki) : null;

  useEffect(() => {
    const el = mountRef.current;
    if (!el || !pose) return;

    const { atoms, bonds } = buildDefaultScene(pose);
    const width = el.clientWidth || 640;
    const height = el.clientHeight || 360;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x070a10);
    scene.fog = new THREE.Fog(0x070a10, 18, 42);

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 200);
    camera.position.set(7.5, 5.5, 9.5);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height, false);
    el.innerHTML = "";
    el.appendChild(renderer.domElement);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.display = "block";
    renderer.domElement.style.touchAction = "none";
    renderer.domElement.style.cursor = "grab";

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0x00e5ff, 1.1);
    key.position.set(6, 10, 4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xfbbf24, 0.35);
    fill.position.set(-6, -2, -4);
    scene.add(fill);

    // Pocket volume hint
    const pocket = new THREE.Mesh(
      new THREE.SphereGeometry(4.2, 32, 24),
      new THREE.MeshStandardMaterial({
        color: 0x00e5ff,
        transparent: true,
        opacity: 0.06,
        roughness: 1,
        side: THREE.DoubleSide,
      }),
    );
    scene.add(pocket);

    const root = new THREE.Group();
    scene.add(root);

    const bySerial = new Map(atoms.map((a) => [a.serial, a]));
    const sphereGeo = new THREE.SphereGeometry(1, 20, 16);

    for (const atom of atoms) {
      const r = ELEMENT_RADIUS[atom.element] ?? 0.32;
      const mat = new THREE.MeshStandardMaterial({
        color: atomColor(atom.element, atom.role),
        roughness: 0.35,
        metalness: atom.role === "ligand" ? 0.35 : 0.1,
        emissive: atom.role === "ligand" ? 0x003344 : 0x000000,
        emissiveIntensity: atom.role === "ligand" ? 0.35 : 0,
      });
      const mesh = new THREE.Mesh(sphereGeo, mat);
      mesh.scale.setScalar(r);
      mesh.position.set(atom.x, atom.y, atom.z);
      root.add(mesh);
    }

    for (const bond of bonds) {
      const aa = bySerial.get(bond.a);
      const bb = bySerial.get(bond.b);
      if (!aa || !bb) continue;
      const a = new THREE.Vector3(aa.x, aa.y, aa.z);
      const b = new THREE.Vector3(bb.x, bb.y, bb.z);
      if (bond.role === "hbond") {
        root.add(makeBondMesh(a, b, 0xfbbf24, 0.04, true));
      } else {
        const color = bond.role === "ligand" ? 0x2dd4bf : 0x64748b;
        root.add(makeBondMesh(a, b, color, bond.role === "ligand" ? 0.07 : 0.05));
      }
    }

    // Fit camera to molecule
    const box = new THREE.Box3().setFromObject(root);
    const center = box.getCenter(new THREE.Vector3());
    root.position.sub(center);
    const size = box.getSize(new THREE.Vector3()).length();
    camera.position.set(size * 0.85, size * 0.55, size * 1.05);
    camera.lookAt(0, 0, 0);

    // Orbit controls (pointer)
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let theta = Math.atan2(camera.position.x, camera.position.z);
    let phi = Math.acos(camera.position.y / camera.position.length());
    let radius = camera.position.length();
    let autoSpin = true;

    const onDown = (e: PointerEvent) => {
      dragging = true;
      autoSpin = false;
      lastX = e.clientX;
      lastY = e.clientY;
      renderer.domElement.setPointerCapture(e.pointerId);
      renderer.domElement.style.cursor = "grabbing";
    };
    const onMove = (e: PointerEvent) => {
      if (!dragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      theta -= dx * 0.008;
      phi = Math.min(Math.PI - 0.12, Math.max(0.12, phi + dy * 0.008));
    };
    const onUp = () => {
      dragging = false;
      renderer.domElement.style.cursor = "grab";
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      radius = Math.min(28, Math.max(4, radius + e.deltaY * 0.01));
      autoSpin = false;
    };

    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerup", onUp);
    renderer.domElement.addEventListener("wheel", onWheel, { passive: false });

    let raf = 0;
    const animate = () => {
      raf = requestAnimationFrame(animate);
      if (autoSpin) theta += 0.004;
      camera.position.set(
        radius * Math.sin(phi) * Math.sin(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.cos(theta),
      );
      camera.lookAt(0, 0, 0);
      pocket.rotation.y += 0.002;
      renderer.render(scene, camera);
    };
    animate();

    const onResize = () => {
      const w = el.clientWidth || width;
      const h = el.clientHeight || height;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(el);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("wheel", onWheel);
      renderer.dispose();
      el.innerHTML = "";
    };
  }, [pose]);

  return (
    <GlassPanel
      title="3D Structural Docking"
      className="min-h-fit h-full"
      bodyClassName="relative min-h-fit space-y-3 overflow-y-auto p-3"
    >
      <div
        ref={mountRef}
        className="relative h-[min(62vh,560px)] min-h-[360px] overflow-hidden rounded-[8px] border border-[rgba(0,240,255,0.22)] bg-[#070A10]"
        data-webgl-root
      >
        {!pose && (
          <p className="flex h-full items-center justify-center text-[13px] text-[#94A3B8]">
            No docking pose loaded.
          </p>
        )}
        {pose && (
          <>
            <p className="pointer-events-none absolute left-3 top-3 z-10 font-mono text-[11px] text-[#94A3B8]">
              Drag to orbit · scroll to zoom · cyan = ligand · amber dashes = H-bonds
            </p>
            {/* Live HUD overlay */}
            <div className="pointer-events-none absolute right-3 top-3 z-10 w-[min(280px,46%)] rounded-[10px] border border-[rgba(0,240,255,0.35)] bg-[rgba(19,27,46,0.92)] p-3 shadow-[0_0_24px_rgba(0,240,255,0.12)] backdrop-blur-md">
              <p className="font-mono text-[10px] tracking-wider text-[#64748B] uppercase">
                Docking HUD
              </p>
              <p className="mt-1 text-[12px] text-[#F8FAFC]">
                Target · <span className="font-mono text-[#00F0FF]">PDB: {pose.receptorId}</span>
              </p>
              <p className="text-[12px] text-[#F8FAFC]">
                Ligand · <span className="font-mono text-[#00E676]">{pose.ligandId}</span>
              </p>
              {dg && (
                <p className="mt-2 font-mono text-[12px] text-[#FFB800]">
                  ΔG = {dg.displayValue} {dg.unit}
                </p>
              )}
              {ki && (
                <p className="font-mono text-[12px] text-[#00F0FF]">
                  Ki = {pose.ki.toExponential(2)} M
                </p>
              )}
            </div>
          </>
        )}
      </div>

      {pose && dg && ki ? (
        <>
          <p className="text-[13px] leading-relaxed text-[#E2E8F0]">
            {dg.plainPhrase}; {ki.plainPhrase}.
          </p>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat
              label={
                <MetricTooltip metric="DG">
                  <span>Binding Free Energy (ΔG)</span>
                </MetricTooltip>
              }
              value={`${dg.displayValue} ${dg.unit}`}
              hint={dg.badgeLabel}
            />
            <Stat
              label={
                <MetricTooltip metric="KI">
                  <span>Inhibition Constant (Ki)</span>
                </MetricTooltip>
              }
              value={`${ki.displayValue} ${ki.unit}`}
              hint={ki.badgeLabel}
            />
            <Stat label="Contacts" value={String(pose.contacts)} />
            <Stat label="H-bonds" value={String(pose.hbonds)} />
          </dl>
          <CollapsibleTelemetry title="Advanced Omics & Raw Biophysical Telemetry">
            <dl className="grid grid-cols-2 gap-2 text-[12px] text-[#94A3B8]">
              <div>
                <dt className={tw.label}>Ligand</dt>
                <dd className={tw.mono}>{pose.ligandId}</dd>
              </div>
              <div>
                <dt className={tw.label}>Receptor</dt>
                <dd className={tw.mono}>{pose.receptorId}</dd>
              </div>
              <div>
                <dt className={tw.label}>ΔG (kcal/mol)</dt>
                <dd className={tw.mono}>{pose.deltaG.toFixed(2)}</dd>
              </div>
              <div>
                <dt className={tw.label}>Ki (M)</dt>
                <dd className={tw.mono}>{pose.ki.toExponential(2)}</dd>
              </div>
              <div>
                <dt className={tw.label}>Atoms</dt>
                <dd className={tw.mono}>{String(pose.atoms?.length ?? "demo")}</dd>
              </div>
            </dl>
          </CollapsibleTelemetry>
        </>
      ) : (
        <p className={tw.label}>Waiting for docking pose…</p>
      )}
    </GlassPanel>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: ReactNode;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-[8px] border border-[rgba(148,163,184,0.12)] bg-[#151C2C] px-2.5 py-2">
      <dt className={tw.label}>{label}</dt>
      <dd className={tw.mono}>{value}</dd>
      {hint && <dd className="mt-0.5 text-[10px] text-[#94A3B8]">{hint}</dd>}
    </div>
  );
}
