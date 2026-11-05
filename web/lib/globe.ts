import type { GlobeData } from "@/components/GlobeLazy";
import type { Countries } from "@/lib/api";

/** Globe inputs from /v1/countries: name-to-code map, counts and city pins. */
export function globeData(countries: Countries): GlobeData {
  return {
    codes: Object.fromEntries(countries.data.map((c) => [c.name, c.code])),
    counts: Object.fromEntries(countries.data.map((c) => [c.code, c.job_count])),
    worldwide: countries.meta.worldwide_remote_jobs,
    pins: countries.data.flatMap((c) => c.cities.map((city) => ({ lat: city.lat, lon: city.lon, count: city.job_count }))),
  };
}
