import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Icon } from './components';
import type { Product, Visual } from './types';

export function ProductPreview({ product, selections }: { product: Product; selections: Record<string, string> }) {
  const container = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false); const [exploded, setExploded] = useState(false);
  const reset = useRef<() => void>(() => undefined);
  const visuals: Visual[] = Array.isArray(product.visual) ? product.visual : Object.entries(product.visual || {}).map(([slot_id, descriptor]) => ({ ...descriptor, slot_id }));
  useEffect(() => {
    const host = container.current;
    if (!host || !visuals.length) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); } catch { setFailed(true); return; }
    setFailed(false);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.01, 1000);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05; renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap; renderer.setClearColor(0x000000, 0); host.appendChild(renderer.domElement);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x657868, 2.5));
    const key = new THREE.DirectionalLight(0xffffff, 3); key.position.set(4, 6, 5); key.castShadow = true; key.shadow.mapSize.set(1024, 1024); scene.add(key);
    const rim = new THREE.DirectionalLight(0xffffff, 1.5); rim.position.set(-5, 2, -3); scene.add(rim);
    const group = new THREE.Group(); scene.add(group);
    const resources: (THREE.BufferGeometry | THREE.Material)[] = [];
    for (const descriptor of visuals) {
      const variant = product.slots.find(slot => slot.id === descriptor.slot_id)?.variants.find(item => item.id === selections[descriptor.slot_id]);
      const geometry = descriptor.primitive === 'sphere' ? new THREE.SphereGeometry(0.5, 32, 20) : descriptor.primitive === 'cylinder' ? new THREE.CylinderGeometry(0.5, 0.5, 1, 40) : descriptor.primitive === 'cone' ? new THREE.ConeGeometry(0.5, 1, 40) : descriptor.primitive === 'torus' ? new THREE.TorusGeometry(0.5, 0.12, 16, 60) : new THREE.BoxGeometry(1, 1, 1);
      const material = new THREE.MeshStandardMaterial({ color: [descriptor.color, variant?.properties.presentation_color, variant?.properties.color].find(value => typeof value === 'string' && value.trim()) as string || '#b9c5b9', roughness: 0.4, metalness: 0.12 });
      const mesh = new THREE.Mesh(geometry, material);
      if (descriptor.position?.length === 3) mesh.position.fromArray(descriptor.position);
      if (descriptor.rotation?.length === 3) mesh.rotation.set(descriptor.rotation[0], descriptor.rotation[1], descriptor.rotation[2]);
      if (descriptor.scale?.length === 3) mesh.scale.fromArray(descriptor.scale);
      if (exploded) { const index = product.slots.findIndex(slot => slot.id === descriptor.slot_id); mesh.position.y += Math.max(0, index) * 0.16; }
      mesh.castShadow = true; group.add(mesh); resources.push(geometry, material);
    }
    const bounds = new THREE.Box3().setFromObject(group); const center = bounds.getCenter(new THREE.Vector3()); const size = bounds.getSize(new THREE.Vector3());
    group.position.sub(center); const radius = Math.max(size.length() / 2, 0.5); let distance = radius * 4;
    const floorGeometry = new THREE.PlaneGeometry(Math.max(size.x, size.z, 1) * 4, Math.max(size.x, size.z, 1) * 4); const floorMaterial = new THREE.ShadowMaterial({ opacity: 0.14 }); const floor = new THREE.Mesh(floorGeometry, floorMaterial); floor.rotation.x = -Math.PI / 2; floor.position.y = -size.y / 2 - 0.02; floor.receiveShadow = true; scene.add(floor); resources.push(floorGeometry, floorMaterial);
    camera.position.set(distance * 0.7, distance * 0.35, distance);
    const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.enablePan = false; controls.minDistance = distance * 0.5; controls.maxDistance = distance * 3;
    const fit = () => { distance = radius / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) / Math.min(1, camera.aspect) * 1.2; camera.position.set(0.65, 0.4, 1).normalize().multiplyScalar(distance); controls.target.set(0, 0, 0); controls.minDistance = radius * 1.2; controls.maxDistance = distance * 3; controls.update(); }; reset.current = fit;
    const resize = () => { const width = host.clientWidth; const height = host.clientHeight; renderer.setSize(width, height); camera.aspect = width / Math.max(height, 1); camera.updateProjectionMatrix(); fit(); };
    const observer = new ResizeObserver(resize); observer.observe(host); resize();
    let frame = 0; const animate = () => { controls.update(); renderer.render(scene, camera); frame = requestAnimationFrame(animate); }; animate();
    return () => { cancelAnimationFrame(frame); observer.disconnect(); controls.dispose(); resources.forEach(item => item.dispose()); renderer.dispose(); renderer.domElement.remove(); };
  // The configured product and selected variants determine every rendered primitive.
  }, [product, selections, exploded]);
  return <div className="product-preview">{visuals.length > 0 && !failed && <div className="preview-controls"><button type="button" onClick={() => reset.current()}>Reset view</button><button type="button" aria-pressed={exploded} onClick={() => setExploded(value => !value)}>{exploded ? 'Assembled preview' : 'Separate parts'}</button></div>}<div className="product-preview__canvas" ref={container} aria-label={`Interactive 3D preview of ${product.name}`}/>{(!visuals.length || failed) && <div className="preview-fallback"><Icon name="box" size={70}/><h3>{product.name}</h3><div>{product.slots.map(slot => { const variant = slot.variants.find(item => item.id === selections[slot.id]); return variant ? <span key={slot.id}><i style={{ background: String(variant.properties.color || '#dde4da') }}/>{variant.name}</span> : null; })}</div></div>}{visuals.length > 0 && !failed && <small className="preview-hint">Drag to rotate · Scroll to zoom<br/>Illustrative geometry — not CAD or verification. {exploded ? 'Separated view is not an assembly sequence.' : ''}</small>}</div>;
}
