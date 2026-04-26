"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, useGLTF } from "@react-three/drei";
import * as THREE from "three";

// ---------------------------------------------------------------------------
// GLB mesh loader — loads and centres the model
// ---------------------------------------------------------------------------

function RoofMesh({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  const meshRef = useRef<THREE.Group>(null);

  useEffect(() => {
    if (!meshRef.current) return;
    const box = new THREE.Box3().setFromObject(meshRef.current);
    const centre = box.getCenter(new THREE.Vector3());
    meshRef.current.position.sub(centre);
  }, [scene]);

  return (
    <primitive
      ref={meshRef}
      object={scene}
      // Highlight the mesh in a solar-gold colour
      onUpdate={(self: THREE.Object3D) => {
        self.traverse((child) => {
          if ((child as THREE.Mesh).isMesh) {
            const mesh = child as THREE.Mesh;
            mesh.material = new THREE.MeshStandardMaterial({
              color: "#f4a300",
              roughness: 0.6,
              metalness: 0.1,
              side: THREE.DoubleSide,
            });
          }
        });
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Camera helper — auto-fits scene to view
// ---------------------------------------------------------------------------

function AutoCamera() {
  const { camera, scene } = useThree();
  useEffect(() => {
    const box = new THREE.Box3().setFromObject(scene);
    const size = box.getSize(new THREE.Vector3()).length();
    const centre = box.getCenter(new THREE.Vector3());
    if (size > 0) {
      (camera as THREE.PerspectiveCamera).near = size / 100;
      (camera as THREE.PerspectiveCamera).far = size * 100;
      camera.position.set(centre.x, centre.y + size * 0.5, centre.z + size * 1.2);
      camera.lookAt(centre);
      camera.updateProjectionMatrix();
    }
  }, [camera, scene]);
  return null;
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

interface Props {
  meshUri: string | null | undefined;
}

export default function RoofMeshViewer({ meshUri }: Props) {
  const [available, setAvailable] = useState<boolean | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const fullUrl = meshUri
    ? meshUri.startsWith("http") ? meshUri : `${apiBase}${meshUri}`
    : null;

  // Probe the artifact endpoint — hide viewer if 404 (reconstruction failed)
  useEffect(() => {
    if (!fullUrl) { setAvailable(false); return; }
    fetch(fullUrl, { method: "HEAD" })
      .then((r) => setAvailable(r.ok))
      .catch(() => setAvailable(false));
  }, [fullUrl]);

  if (!available) return null;

  return (
    <section className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-semibold text-gray-800 mb-3">3D Roof Model</h2>
      <div className="w-full h-80 rounded overflow-hidden bg-gray-900">
        <Canvas camera={{ fov: 50 }} shadows>
          <ambientLight intensity={0.6} />
          <directionalLight position={[5, 10, 5]} intensity={1.2} castShadow />
          <Suspense
            fallback={
              <mesh>
                <boxGeometry args={[1, 0.1, 1]} />
                <meshStandardMaterial color="#ccc" />
              </mesh>
            }
          >
            <RoofMesh url={fullUrl!} />
            <AutoCamera />
          </Suspense>
          <OrbitControls makeDefault />
          <gridHelper args={[20, 20, "#444", "#222"]} />
        </Canvas>
      </div>
      <p className="text-xs text-gray-400 mt-2">
        Drag to rotate · Scroll to zoom · Right-click to pan
      </p>
    </section>
  );
}
