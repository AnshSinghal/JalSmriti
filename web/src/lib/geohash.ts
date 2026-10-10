const B32 = "0123456789bcdefghjkmnpqrstuvwxyz";

/** Same as the server's geo.geohash: the id of a followed place is its 7-character geohash (about 150 m). */
export function geohash(lat: number, lon: number, precision = 7): string {
  const latR = [-90, 90], lonR = [-180, 180];
  let bits = 0, ch = 0, even = true, out = "";
  while (out.length < precision) {
    const r = even ? lonR : latR, v = even ? lon : lat;
    const mid = (r[0] + r[1]) / 2;
    if (v >= mid) { ch |= 1 << (4 - bits); r[0] = mid; } else { r[1] = mid; }
    even = !even;
    if (++bits === 5) { out += B32[ch]; bits = 0; ch = 0; }
  }
  return out;
}
