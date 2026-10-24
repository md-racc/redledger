"use client";
// Client-only entry: the arena needs WebGL, window and the DOM, so it never renders on the server.
import dynamic from "next/dynamic";

const ArenaExperience = dynamic(() => import("./ArenaExperience"), {
  ssr: false,
  loading: () => <div className="boot" aria-label="Loading redledger" />,
});

export default function ArenaClient() {
  return <ArenaExperience />;
}
