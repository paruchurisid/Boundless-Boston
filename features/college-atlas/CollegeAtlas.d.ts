import type { CSSProperties } from 'react';
import type maplibre from 'maplibre-gl';
export function CollegeAtlas(props: {
  maplibre: typeof maplibre;
  onCampusChange?: (campus: { name: string; lat: number; lng: number } | null) => void;
  className?: string;
  style?: CSSProperties;
}): import('react').ReactElement;
