// Small bridge from the 3D scene to the DOM overlays (screen positions of agents).
export interface ScreenPoint { x: number; y: number; z: number }
export const bridge: { project: (id: string) => ScreenPoint | null } = { project: () => null };
