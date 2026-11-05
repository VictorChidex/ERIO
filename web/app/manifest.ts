import type { MetadataRoute } from "next";

// Lets phones add ERIO to the home screen with its own name and icon.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "ERIO — jobs in every country",
    short_name: "ERIO",
    description: "Search open jobs from employers' own job boards in every country.",
    start_url: "/",
    display: "standalone",
    background_color: "#060a12",
    theme_color: "#060a12",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml" },
      { src: "/apple-icon", sizes: "180x180", type: "image/png" },
    ],
  };
}
