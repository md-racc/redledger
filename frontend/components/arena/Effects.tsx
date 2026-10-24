"use client";
// Post chain: HDR bloom (the agents' emissives and beacons), filmic tone mapping, grade, vignette, grain, SMAA.
// "lite" keeps bloom + tone mapping only; "off" is handled by the renderer's own tone mapping (see Scene.tsx).
import { BrightnessContrast, Bloom, EffectComposer, HueSaturation, Noise, SMAA, ToneMapping, Vignette } from "@react-three/postprocessing";
import { BlendFunction, ToneMappingMode } from "postprocessing";
import type { Quality } from "@/lib/arena/quality";

export function Effects({ mode }: { mode: Quality["post"] }) {
  if (mode === "off") return null;
  if (mode === "lite") {
    return (
      <EffectComposer multisampling={0} enableNormalPass={false}>
        <Bloom mipmapBlur intensity={0.8} luminanceThreshold={0.9} luminanceSmoothing={0.25} radius={0.6} />
        <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      </EffectComposer>
    );
  }
  return (
    <EffectComposer multisampling={0} enableNormalPass={false}>
      <Bloom mipmapBlur intensity={0.85} luminanceThreshold={0.9} luminanceSmoothing={0.25} radius={0.7} />
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <HueSaturation saturation={0.16} hue={0} />
      <BrightnessContrast brightness={-0.02} contrast={0.14} />
      <Vignette eskil={false} offset={0.22} darkness={0.62} />
      <Noise premultiply blendFunction={BlendFunction.SOFT_LIGHT} opacity={0.35} />
      <SMAA />
    </EffectComposer>
  );
}
