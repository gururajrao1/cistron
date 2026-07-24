declare module '3dmol/build/3Dmol.js' {
  const $3Dmol: {
    createViewer: (
      element: HTMLElement,
      config?: Record<string, unknown>,
    ) => {
      addModel: (data: string, format: string) => unknown
      setStyle: (sel: object, style: object) => void
      addSurface?: (...args: unknown[]) => Promise<unknown> | unknown
      removeAllSurfaces?: () => void
      zoomTo: (sel?: object) => void
      zoom: (factor: number, animationDuration?: number) => void
      render: () => void
      clear: () => void
      resize?: () => void
      setBackgroundColor?: (c: string | number) => void
      setClickable?: (
        sel: object,
        clickable: boolean,
        callback?: (atom: { resi?: number; resn?: string }) => void,
      ) => void
    }
    SurfaceType?: { VDW?: unknown; SAS?: unknown }
    ssColors?: { Jmol?: unknown }
  }
  export default $3Dmol
}
