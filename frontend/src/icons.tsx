/* Hand-drawn duotone icon set.
 *
 * Each icon is a 24×24 drawing in two layers: a soft translucent "glass" body
 * (currentColor at low opacity) and a crisp 1.7px outline on top, with one small
 * accent mark.  They inherit colour from CSS, so they follow the theme.
 */
import type {ReactNode} from 'react';

type IconProps = {size?: number; className?: string};

function Glyph({size = 20, className = '', children}: IconProps & {children: ReactNode}) {
  return <svg className={'glyph ' + className} width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}

const body = {fill: 'currentColor', fillOpacity: 0.16, stroke: 'none'} as const;
const accent = {fill: 'var(--glyph-accent, currentColor)', stroke: 'none'} as const;

/** Overview: a tide gauge — a dial with the water line and the reading needle. */
export const IconOverview = (p: IconProps) => <Glyph {...p}>
  <circle cx="12" cy="12" r="9" {...body}/>
  <circle cx="12" cy="12" r="9"/>
  <path d="M4.2 14.6c1.6-1.3 3-1.3 4.6 0s3 1.3 4.6 0 3-1.3 4.6 0 1.6 1 2 1"/>
  <path d="M12 12.2 15.6 7.4"/>
  <circle cx="12" cy="12.2" r="1.5" {...accent}/>
</Glyph>;

/** Updates: ripples spreading from a single drop. */
export const IconUpdates = (p: IconProps) => <Glyph {...p}>
  <ellipse cx="12" cy="15.5" rx="9" ry="4.2" {...body}/>
  <ellipse cx="12" cy="15.5" rx="9" ry="4.2"/>
  <ellipse cx="12" cy="15.5" rx="4.6" ry="2"/>
  <path d="M12 3.2c1.7 2.2 2.6 3.7 2.6 4.9a2.6 2.6 0 0 1-5.2 0c0-1.2.9-2.7 2.6-4.9Z" {...accent}/>
</Glyph>;

/** Library: two stacked documents, the front one sealed. */
export const IconLibrary = (p: IconProps) => <Glyph {...p}>
  <path d="M8 3.5h7.5L19.5 7.5V17a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 17V5A1.5 1.5 0 0 1 8 3.5Z" {...body}/>
  <path d="M4.5 7.5V19A1.5 1.5 0 0 0 6 20.5h9.5"/>
  <path d="M8 3.5h7.5L19.5 7.5V17a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 17V5A1.5 1.5 0 0 1 8 3.5Z"/>
  <path d="M9.5 9h4.5M9.5 12h6.5"/>
  <rect x="13.4" y="13.6" width="3.6" height="3.6" rx=".8" {...accent}/>
</Glyph>;

/** Columns: three pillars of different heights standing in water. */
export const IconColumns = (p: IconProps) => <Glyph {...p}>
  <rect x="4" y="9" width="4" height="10" rx="1.2" {...body}/>
  <rect x="10" y="4.5" width="4" height="14.5" rx="1.2" {...body}/>
  <rect x="16" y="11.5" width="4" height="7.5" rx="1.2" {...body}/>
  <rect x="4" y="9" width="4" height="10" rx="1.2"/>
  <rect x="10" y="4.5" width="4" height="14.5" rx="1.2"/>
  <rect x="16" y="11.5" width="4" height="7.5" rx="1.2"/>
  <path d="M2.5 21.2c1.5-.9 3-.9 4.5 0s3 .9 4.5 0 3-.9 4.5 0 3 .9 5 0"/>
  <circle cx="12" cy="7.6" r="1.1" {...accent}/>
</Glyph>;

/** Mail: an envelope whose flap is a wave crest. */
export const IconMail = (p: IconProps) => <Glyph {...p}>
  <rect x="3" y="5.5" width="18" height="13" rx="2.5" {...body}/>
  <rect x="3" y="5.5" width="18" height="13" rx="2.5"/>
  <path d="M3.8 7.2c2.6 2.6 4.6 4.4 6.4 4.4 1.2 0 1.6-1 2.8-1s2 1 3.4.2l3.8-3.6"/>
  <circle cx="18.6" cy="5.4" r="2.6" {...accent}/>
</Glyph>;

/** Runs: a heartbeat trace inside a log card. */
export const IconRuns = (p: IconProps) => <Glyph {...p}>
  <rect x="3" y="4" width="18" height="16" rx="3" {...body}/>
  <rect x="3" y="4" width="18" height="16" rx="3"/>
  <path d="M5.5 12.5h3l1.6-3.6 2.6 7.2 1.8-3.6h4"/>
  <circle cx="18.6" cy="12.5" r="1.3" {...accent}/>
</Glyph>;

/** Refresh: a wave folding back on itself. */
export const IconRefresh = (p: IconProps) => <Glyph {...p}>
  <path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/>
  <path d="M19.8 4.2v4.2h-4.2"/>
  <path d="M8.4 12.8c1.2-1 2.4-1 3.6 0s2.4 1 3.6 0"/>
</Glyph>;

/** Attention: a buoy. */
export const IconBuoy = (p: IconProps) => <Glyph {...p}>
  <path d="M8 18.5 9.6 8h4.8L16 18.5Z" {...body}/>
  <path d="M8 18.5 9.6 8h4.8L16 18.5"/>
  <path d="M9 13.2h6"/>
  <path d="M12 8V4.5"/>
  <circle cx="12" cy="3.6" r="1.4" {...accent}/>
  <path d="M3 20.5c1.5-.9 3-.9 4.5 0s3 .9 4.5 0 3-.9 4.5 0 3 .9 4.5 0"/>
</Glyph>;

/** Empty inbox: a calm horizon. */
export const IconCalm = (p: IconProps) => <Glyph {...p}>
  <circle cx="12" cy="11" r="4.5" {...body}/>
  <path d="M7.5 11a4.5 4.5 0 0 1 9 0"/>
  <path d="M3 14.5h18"/>
  <path d="M6 17.8h12M9 20.6h6"/>
</Glyph>;

/** Attachment / file. */
export const IconFile = (p: IconProps) => <Glyph {...p}>
  <path d="M7 3h7l5 5v11.5A1.5 1.5 0 0 1 17.5 21h-10.5A1.5 1.5 0 0 1 5.5 19.5V4.5A1.5 1.5 0 0 1 7 3Z" {...body}/>
  <path d="M7 3h7l5 5v11.5A1.5 1.5 0 0 1 17.5 21h-10.5A1.5 1.5 0 0 1 5.5 19.5V4.5A1.5 1.5 0 0 1 7 3Z"/>
  <path d="M14 3v5h5"/>
  <path d="M8.6 13.6c1-.8 2-.8 3 0s2 .8 3 0"/>
  <path d="M8.6 16.8h5"/>
</Glyph>;

/** Versions: layered sheets offset like waves. */
export const IconVersions = (p: IconProps) => <Glyph {...p}>
  <path d="M12 3.5 21 8l-9 4.5L3 8Z" {...body}/>
  <path d="M12 3.5 21 8l-9 4.5L3 8Z"/>
  <path d="m3 12 9 4.5 9-4.5"/>
  <path d="m3 16 9 4.5 9-4.5"/>
</Glyph>;

/** Brand mark: an eye made of two wave arcs, its pupil the rising sun. */
export function BrandMark({size = 40}: {size?: number}) {
  return <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" className="brand-svg">
    <defs>
      <linearGradient id="bm-sea" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#5aa8ff"/><stop offset=".55" stopColor="#1f6fe8"/><stop offset="1" stopColor="#123f9e"/>
      </linearGradient>
      <radialGradient id="bm-sun" cx=".5" cy=".4" r=".6">
        <stop offset="0" stopColor="#fff7e0"/><stop offset=".6" stopColor="#ffd27a"/><stop offset="1" stopColor="#ff9f43"/>
      </radialGradient>
      <linearGradient id="bm-shine" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#fff" stopOpacity=".55"/><stop offset=".5" stopColor="#fff" stopOpacity="0"/>
      </linearGradient>
    </defs>
    <rect x="1" y="1" width="46" height="46" rx="13" fill="url(#bm-sea)"/>
    <rect x="1" y="1" width="46" height="46" rx="13" fill="url(#bm-shine)"/>
    <path d="M7 24c5-7.5 10.6-11 17-11s12 3.5 17 11" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round"/>
    <circle cx="24" cy="24" r="6.2" fill="url(#bm-sun)"/>
    <path d="M7 27.5c3 2.4 5.8 2.4 8.6 0s5.7-2.4 8.4 0 5.7 2.4 8.4 0 5.6-2.4 8.6 0" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round"/>
    <path d="M10.5 34c2.3 1.8 4.5 1.8 6.8 0s4.5-1.8 6.7 0 4.5 1.8 6.7 0 4.5-1.8 6.8 0" fill="none" stroke="#fff" strokeOpacity=".6" strokeWidth="2.2" strokeLinecap="round"/>
  </svg>;
}
