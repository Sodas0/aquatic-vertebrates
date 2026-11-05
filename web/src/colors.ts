// Overlay colors, drawn on top of photos: bright fills over a dark halo so they read on white trays,
// water and rocks. Pending vs accepted differ in hue AND lightness (amber vs sky blue), which stays
// distinguishable with common color-vision deficiencies. No dashed lines.
export const LINE = {
  pending: '#FFB000',   // amber: still to review
  accepted: '#38BDF8',  // sky blue: accepted
  rejected: '#A8A29E',  // stone gray, drawn faded: rejected
} as const;
export const HALO = '#0B0B0A';
export const SNOUT = '#FF3B30';
export const TAIL = '#FFFFFF';
export const RULER = '#F0529C';
export const DRAFT = '#FFFFFF';
export const VENT = '#A855F7';
