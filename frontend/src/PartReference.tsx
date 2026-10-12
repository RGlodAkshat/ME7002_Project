import type { Part } from './types';

/** Visual aid only: configured photographs win; drawings never assert physical correctness. */
export function PartReference({ part, caption = false }: { part: Part; caption?: boolean }) {
  const name = `${part.slot_id} ${part.name}`.toLowerCase(); const color = part.color || (/gear/.test(name) ? '#edc340' : '#5c927b');
  const gear = /gear/.test(name); const blade = /blade|propeller/.test(name); const pin = /pin/.test(name); const handle = /handle/.test(name); const casing = /base|upper|casing|plate/.test(name);
  const teeth = Array.from({ length: 48 }, (_, index) => { const angle = Math.PI * 2 * index / 48; const radius = index % 4 < 2 ? 77 : 65; return `${100 + Math.cos(angle) * radius},${100 + Math.sin(angle) * radius}`; }).join(' ');
  return <figure className={`part-reference ${caption ? 'part-reference--detailed' : ''}`}>
    {part.image_url ? <img src={part.image_url} alt={`Configured reference for ${part.name}`}/> : <svg viewBox="0 0 200 200" role="img" aria-label={`Illustrative drawing of ${part.name}`}>
      {gear ? <><polygon points={teeth} fill={color} stroke="#254437" strokeWidth="3"/><circle cx="100" cy="100" r="19" fill="#f5f8ef" stroke="#254437" strokeWidth="3"/></> : blade ? <g fill={color} stroke="#254437" strokeWidth="2">{Array.from({ length: 6 }, (_, index) => <path key={index} d="M100 100 L119 30 Q167 43 149 75 Z" transform={`rotate(${index * 60} 100 100)`}/>)}<circle cx="100" cy="100" r="16" fill="#f5f8ef"/></g> : pin ? <><rect x="74" y="39" width="52" height="124" rx="8" fill={color} stroke="#254437" strokeWidth="3"/><ellipse cx="100" cy="40" rx="26" ry="10" fill="#dbe7dd" stroke="#254437" strokeWidth="3"/><path d="M85 54 V149" stroke="#ffffff88" strokeWidth="5"/></> : handle ? <path d="M65 35 V135 Q65 159 89 159 H144" fill="none" stroke={color} strokeWidth="29" strokeLinecap="round"/> : casing ? <><rect x="16" y="61" width="168" height="79" rx="34" fill={color} stroke="#254437" strokeWidth="3"/><circle cx="58" cy="101" r="20" fill="#f5f8ef"/><circle cx="115" cy="101" r="23" fill="#f5f8ef"/><path d="M155 75V126" stroke="#f5f8ef" strokeWidth="8"/></> : <><path d="M100 29L174 69V140L100 181L26 140V69Z" fill={color} stroke="#254437" strokeWidth="3"/><path d="M26 69L100 110L174 69M100 110V181" fill="none" stroke="#254437" strokeWidth="3"/></>}
    </svg>}
    {caption && <figcaption>{part.image_url ? 'Configured reference photograph' : 'Illustrative part reference — confirm the physical part and bin label.'}</figcaption>}
  </figure>;
}
