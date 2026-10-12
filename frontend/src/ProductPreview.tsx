import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Icon } from './components';
import type { Product, Visual } from './types';

export function ProductPreview({ product, selections }: { product: Product; selections: Record<string, string> }) {
  const container = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const visuals: Visual[] = Array.isArray(product.visual) ? product.visual : Object.entries(product.visual || {}).map(([slot_id, descriptor]) => ({ ...descriptor, slot_id }));
  useEffect(() => {
    const host = container.current;
    if (!host || !visuals.length) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); } catch { setFailed(true); return; }
    setFailed(false);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.01, 1000);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); renderer.setClearColor(0x000000, 0); host.appendChild(renderer.domElement);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x657868, 2.5));
    const key = new THREE.DirectionalLight(0xffffff, 3); key.position.set(4, 6, 5); scene.add(key);
    const group = new THREE.Group(); scene.add(group);
    const resources: (THREE.BufferGeometry | THREE.Material)[] = [];
    for (const descriptor of visuals) {
      const variant = product.slots.find(slot => slot.id === descriptor.slot_id)?.variants.find(item => item.id === selections[descriptor.slot_id]);
      const geometry = descriptor.primitive === 'sphere' ? new THREE.SphereGeometry(0.5, 32, 20) : descriptor.primitive === 'cylinder' ? new THREE.CylinderGeometry(0.5, 0.5, 1, 40) : descriptor.primitive === 'cone' ? new THREE.ConeGeometry(0.5, 1, 40) : descriptor.primitive === 'torus' ? new THREE.TorusGeometry(0.5, 0.12, 16, 60) : new THREE.BoxGeometry(1, 1, 1);
      const material = new THREE.MeshStandardMaterial({ color: typeof variant?.properties.color === 'string' ? variant.properties.color : '#b9c5b9', roughness: 0.4, metalness: 0.12 });
      const mesh = new THREE.Mesh(geometry, material);
      if (descriptor.position?.length === 3) mesh.position.fromArray(descriptor.position);
      if (descriptor.rotation?.length === 3) mesh.rotation.set(descriptor.rotation[0], descriptor.rotation[1], descriptor.rotation[2]);
      if (descriptor.scale?.length === 3) mesh.scale.fromArray(descriptor.scale);
      group.add(mesh); resources.push(geometry, material);
    }
    const bounds = new THREE.Box3().setFromObject(group); const center = bounds.getCenter(new THREE.Vector3()); const size = bounds.getSize(new THREE.Vector3());
    group.position.sub(center); const distance = Math.max(size.x, size.y, size.z, 1) * 2.9;
    camera.position.set(distance * 0.7, distance * 0.35, distance);
    const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.enablePan = false; controls.minDistance = distance * 0.5; controls.maxDistance = distance * 3;
    const resize = () => { const width = host.clientWidth; const height = host.clientHeight; renderer.setSize(width, height); camera.aspect = width / Math.max(height, 1); camera.updateProjectionMatrix(); };
    const observer = new ResizeObserver(resize); observer.observe(host); resize();
    let frame = 0; const animate = () => { controls.update(); renderer.render(scene, camera); frame = requestAnimationFrame(animate); }; animate();
    return () => { cancelAnimationFrame(frame); observer.disconnect(); controls.dispose(); resources.forEach(item => item.dispose()); renderer.dispose(); renderer.domElement.remove(); };
  // The configured product and selected variants determine every rendered primitive.
  }, [product, selections]);
  return <div className="product-preview"><div className="product-preview__canvas" ref={container} aria-label={`Interactive 3D preview of ${product.name}`}/>{(!visuals.length || failed) && <div className="preview-fallback"><Icon name="box" size={70}/><h3>{product.name}</h3><div>{product.slots.map(slot => { const variant = slot.variants.find(item => item.id === selections[slot.id]); return variant ? <span key={slot.id}><i style={{ background: String(variant.properties.color || '#dde4da') }}/>{variant.name}</span> : null; })}</div></div>}{visuals.length > 0 && !failed && <small className="preview-hint">Drag to rotate · Scroll to zoom<br/>Configuration preview; proportions are illustrative.</small>}</div>;
}
